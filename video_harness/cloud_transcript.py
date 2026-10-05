"""Source-bound OpenAI/Azure transcription with separate text and word timing calls."""
from pathlib import Path
import fcntl
import hashlib
import json
import math
import os
import re

from .common import ROOT, fingerprint, probe, run
from .media import stream_bounds
from .privacy import require_cloud_permission
from .transcript import load_transcript, save_transcript

CHUNK_SECONDS = 300.0
MAX_UPLOAD_BYTES = 25_000_000


class ProviderFailure(RuntimeError):
    """A cloud request or unusable provider response permits the next provider."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _payload(response):
    if isinstance(response, dict):
        return response
    if hasattr(response, 'model_dump'):
        return response.model_dump(mode='json')
    raise ValueError('Unsupported transcription response')


def _client(provider, timeout, max_retries):
    import openai
    if provider == 'openai':
        key = os.environ.get('OPENAI_API_KEY')
        if not key:
            raise ValueError('OPENAI_API_KEY is required')
        return openai.OpenAI(api_key=key, timeout=timeout, max_retries=max_retries), getattr(openai, '__version__', 'unknown')
    if provider == 'azure':
        names = ('AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT', 'AZURE_OPENAI_TIMESTAMP_DEPLOYMENT')
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError('Azure transcription configuration missing: ' + ', '.join(missing))
        return openai.AzureOpenAI(azure_endpoint=os.environ[names[0]], api_key=os.environ[names[1]],
                                  api_version=os.environ.get('AZURE_OPENAI_API_VERSION', '2025-04-01-preview'),
                                  timeout=timeout, max_retries=max_retries), getattr(openai, '__version__', 'unknown')
    raise ValueError('Provider must be openai or azure')


def _models(cfg, provider):
    cloud = cfg.get('transcription', {})
    if provider == 'openai':
        return cloud.get('cloud_model', 'gpt-transcribe'), cloud.get('timing_model', 'whisper-1')
    return os.environ.get('AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT'), os.environ.get('AZURE_OPENAI_TIMESTAMP_DEPLOYMENT')


def _chunks(duration):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid source duration')
    rounded = round(duration, 6)
    if rounded <= 0:
        raise ValueError('Source is shorter than supported timing precision')
    count = math.ceil(rounded / CHUNK_SECONDS)
    return [(round(index * CHUNK_SECONDS, 6), round(min(CHUNK_SECONDS, rounded - index * CHUNK_SECONDS), 6))
            for index in range(count)]


def _normalize(value):
    return re.sub(r'\W+', '', value, flags=re.UNICODE).casefold()


def _bounded_time(raw, offset, length, duration, label):
    try:
        start, end = float(raw['start']), float(raw['end'])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f'Invalid {label} timestamp') from None
    if not all(math.isfinite(value) for value in (start, end)) or not 0 <= start <= end <= length:
        raise ValueError(f'Invalid {label} timestamp outside chunk: start={start}, end={end}, length={length}')
    absolute_start, absolute_end = round(offset + start, 6), round(offset + end, 6)
    if absolute_end > duration + 1e-6:
        raise ValueError(f'Invalid {label} timestamp beyond source')
    return absolute_start, min(absolute_end, duration)


def _check_timing_response(timing, length):
    for kind in ('words', 'segments'):
        for row in timing.get(kind) or []:
            _bounded_time(row, 0, length, length, kind[:-1])


def _request_pair(client, path, provider, text_model, timing_model, language):
    text_args = {'model': text_model, 'response_format': 'json'}
    if provider == 'openai' and text_model == 'gpt-transcribe':
        text_args['extra_body'] = {'languages': [language]}
    else:
        text_args['language'] = language
    with path.open('rb') as media:
        semantic = _payload(client.audio.transcriptions.create(file=media, **text_args))
    with path.open('rb') as media:
        timing = _payload(client.audio.transcriptions.create(
            file=media, model=timing_model, language=language, response_format='verbose_json',
            timestamp_granularities=['word', 'segment']))
    return semantic, timing


def _cache_pair(folder, index, client, path, provider, text_model, timing_model,
                language, offset, length, source_id, verify_only=False):
    metadata = {'provider': provider, 'text_model': text_model, 'timing_model': timing_model,
                'audio_sha256': fingerprint(path)['sha256'], 'index': index,
                'language': language, 'offset': offset, 'length': length,
                'source_sha256': source_id['sha256']}
    raw = folder / f'chunk-{index:04d}-responses.json'
    seal = folder / f'chunk-{index:04d}-manifest.json'
    if raw.is_file() and seal.is_file():
        saved = json.loads(raw.read_text())
        manifest = json.loads(seal.read_text())
        legacy = {key: metadata[key] for key in ('provider', 'text_model', 'timing_model', 'audio_sha256', 'index')}
        if manifest.get('response_sha256') == _hash(saved) and manifest.get('request') in (metadata, legacy):
            _check_timing_response(saved['timing'], length)
            return saved['semantic'], saved['timing']
        raise ValueError('Cached transcription response changed')
    if raw.exists() or seal.exists() or verify_only:
        raise ValueError('Cached transcription response incomplete')
    try:
        semantic, timing = _request_pair(client, path, provider, text_model, timing_model, language)
    except OSError:
        raise
    except Exception as exc:
        raise ProviderFailure(f'{provider} transcription request failed for chunk {index}; credentials and response are not logged', getattr(exc, 'status_code', None)) from None
    if not isinstance(semantic.get('text'), str) or not semantic['text'].strip():
        raise ProviderFailure('Cloud transcription returned no semantic text')
    try:
        _check_timing_response(timing, length)
    except ValueError:
        raise ProviderFailure('Provider returned invalid timed words') from None
    saved = {'semantic': semantic, 'timing': timing}
    raw.write_text(json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False))
    seal.write_text(json.dumps({'request': metadata, 'response_sha256': _hash(saved)}, ensure_ascii=False, indent=2))
    return semantic, timing


def transcribe_cloud(cfg, provider, cache_root=None):
    """Make two API requests per audio chunk; return immutable transcript JSON path."""
    if provider not in ('openai', 'azure'):
        raise ValueError('Provider must be openai or azure')
    require_cloud_permission(cfg, provider)
    permission = cfg['cloud_permission']
    options = cfg.get('transcription', {})
    language = options.get('language', 'ja')
    if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2,3}(?:-[a-z]{2})?', language):
        raise ValueError('Invalid transcription language')
    timeout = float(options.get('request_timeout_seconds', 120))
    max_retries = options.get('max_retries', 1)
    if not math.isfinite(timeout) or not 1 <= timeout <= 300 or type(max_retries) is not int or not 0 <= max_retries <= 3:
        raise ValueError('Invalid cloud request timeout or retry limit')
    source = Path(cfg['source']).resolve()
    source_id = fingerprint(source)
    info = probe(source)
    duration = float(info['format']['duration'])
    spans = _chunks(duration)
    format_start = float(info['format'].get('start_time', 0))
    video_range, audio_range = stream_bounds(info, 'video'), stream_bounds(info, 'audio')
    if not math.isfinite(format_start) or abs(format_start) > 0.01 or video_range is None or audio_range is None:
        raise ValueError('Cloud transcription requires full-length zero-start video and audio tracks')
    if any(abs(bounds[0]) > 0.01 or abs(bounds[1] - duration) > 0.15 for bounds in (video_range, audio_range)):
        raise ValueError('Cloud transcription requires full-length zero-start video and audio tracks')
    text_model, timing_model = _models(cfg, provider)
    if not text_model or not timing_model:
        raise ValueError('Cloud transcription model deployments are required')
    if provider == 'openai' and timing_model != 'whisper-1':
        raise ValueError('Word timing model must be whisper-1')
    key = _hash({'source': source_id, 'duration': duration, 'provider': provider,
                 'text_model': text_model, 'timing_model': timing_model, 'language': language})
    folder = Path(cache_root) / key if cache_root is not None else ROOT / 'output' / 'transcripts' / key
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.cache.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _transcribe_locked(folder, source, source_id, duration, spans, provider,
                                  text_model, timing_model, language, timeout, max_retries, permission)


def _transcribe_locked(folder, source, source_id, duration, spans, provider,
                       text_model, timing_model, language, timeout, max_retries, permission):
    result = folder / 'transcript.json'
    if result.exists():
        load_transcript(result, source)
        for index, (offset, length) in enumerate(spans):
            audio = folder / f'chunk-{index:04d}.mp3'
            if not audio.is_file():
                raise ValueError('Cached audio chunk missing')
            _cache_pair(folder, index, None, audio, provider, text_model, timing_model,
                        language, offset, length, source_id, verify_only=True)
        return result
    client, version = _client(provider, timeout, max_retries)
    semantic_parts, words, segments = [], [], []
    warnings = ['Timed word confidence unavailable; probability 0.0 is a schema placeholder, not a measured score.']
    last_word_end = 0.0
    for index, (offset, length) in enumerate(spans):
        audio = folder / f'chunk-{index:04d}.mp3'
        if not audio.exists():
            run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-ss', str(offset), '-i', str(source),
                 '-t', str(length), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'libmp3lame',
                 '-b:a', '64k', '-y', str(audio)], folder / f'chunk-{index:04d}-extract.log')
        if not audio.is_file() or audio.stat().st_size == 0 or audio.stat().st_size > MAX_UPLOAD_BYTES:
            raise ValueError('Audio chunk missing, empty, or exceeds provider upload limit')
        if fingerprint(source) != source_id:
            raise ValueError('Source changed before cloud upload')
        require_cloud_permission({'source': str(source), 'cloud_permission': permission}, provider)
        semantic, timing = _cache_pair(folder, index, client, audio, provider, text_model, timing_model,
                                       language, offset, length, source_id)
        semantic_parts.append(str(semantic.get('text') or '').strip())
        timed_text = str(timing.get('text') or '').strip()
        if _normalize(semantic_parts[-1]) != _normalize(timed_text):
            warnings.append(f'Chunk {index}: semantic text differs from timing transcript; review against audio.')
        for raw in timing.get('words') or []:
            text = str(raw.get('word') or raw.get('text') or '').strip()
            start, end = _bounded_time(raw, offset, length, duration, 'word')
            if not text or end <= start or start < last_word_end:
                warnings.append(f'Chunk {index}: skipped empty or overlapping timed word; review audio.')
                continue
            words.append({'id': len(words) + 1, 'start': start, 'end': end,
                          'text': text, 'probability': 0.0})
            last_word_end = end
        for raw in timing.get('segments') or []:
            text = str(raw.get('text') or '').strip()
            start, end = _bounded_time(raw, offset, length, duration, 'segment')
            if text and end > start:
                segments.append({'id': len(segments) + 1, 'start': start, 'end': end, 'text': text})
    if fingerprint(source) != source_id:
        raise ValueError('Source changed during transcription')
    if not any(semantic_parts):
        raise ProviderFailure('Cloud transcription returned no semantic text')
    if not words:
        raise ProviderFailure('Cloud timing request returned no words')
    data = {'version': 1, 'source': source_id, 'duration': duration, 'language': language,
            'backend': {'name': provider, 'sdk_version': version,
                        'settings': {'text_model': text_model, 'timing_model': timing_model,
                                     'chunk_seconds': CHUNK_SECONDS, 'audio_format': 'mp3', 'audio_bitrate': '64k',
                                     'language': language, 'request_timeout_seconds': timeout, 'max_retries': max_retries,
                                     'word_probability_available': False,
                                     'api_version': os.environ.get('AZURE_OPENAI_API_VERSION', '2025-04-01-preview') if provider == 'azure' else None}},
            'semantic_text': '\n'.join(part for part in semantic_parts if part),
            'words': words, 'segments': segments, 'warnings': warnings, 'status': 'review_required'}
    return save_transcript(folder, data)
