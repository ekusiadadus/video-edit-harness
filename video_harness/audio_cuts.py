"""Source-bound J/L audio handles, with explicit word and sample provenance."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import copy
import math
import subprocess
import wave

from .common import fingerprint, probe
from .render_cache import digest

RATE = 48000
EVENT_FIELDS = {'id', 'kind', 'before_sequence_id', 'duration_frames', 'reason',
                'handle_observation', 'replacement_observation', 'handle_word_ids',
                'repeat_word_ids', 'handle_audio_kind'}


def _fraction(value):
    if isinstance(value, bool):
        raise ValueError('Invalid time')
    try:
        result = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid time') from exc
    if not math.isfinite(float(result)):
        raise ValueError('Invalid time')
    return result


def _sample(value):
    return round(_fraction(value) * RATE)


def _source(cfg, asset_id=None, *, require_audio=False):
    if asset_id is None:
        path = cfg['source']
        expected = None
    else:
        asset = next((a for a in cfg.get('assets', []) if a['asset_id'] == asset_id), None)
        if asset is None:
            raise ValueError('Unknown visual source asset')
        path, expected = asset['path'], asset['sha256']
    identity = fingerprint(path)
    if expected is not None and identity['sha256'] != expected:
        raise ValueError('Source asset changed')
    info = probe(path)
    audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    if audio is None and require_audio:
        raise ValueError('Audio handle source has no audio track')
    if audio is None:
        audio = next(s for s in info['streams'] if s['codec_type'] == 'video')
    start = _fraction(audio.get('start_time', '0'))
    duration = _fraction(audio.get('duration') or info['format'].get('duration'))
    if abs(start) > Fraction(1, 100) or duration <= 0:
        raise ValueError('Audio handle needs a zero-start audio track')
    return identity, duration


def _rows(mapping, plan, cfg):
    if mapping.get('retime') or cfg.get('retime'):
        raise ValueError('Audio handles require an unretimed mapping')
    if mapping.get('audio_cuts'):
        raise ValueError('Audio handles already applied to mapping')
    visual = mapping.get('edit_basis') == 'visual'
    if visual:
        source_rows = mapping['sequence']
        fps = _fraction(mapping['fps'])
        if len(source_rows) != len(plan['sequence']):
            raise ValueError('Visual sequence and mapping differ')
        rows = []
        for source_row, item in zip(source_rows, plan['sequence']):
            if source_row['id'] != item['id']:
                raise ValueError('Visual sequence and mapping differ')
            source_fps = _fraction(source_row['source_fps'])
            first = source_row['source_first_frame']
            last = source_row['source_end_frame_exclusive']
            out_first = source_row['output_first_frame']
            out_last = source_row['output_end_frame_exclusive']
            if any(type(n) is not int for n in (first, last, out_first, out_last)) or first < 0 or last <= first or out_first < 0 or out_last <= out_first:
                raise ValueError('Invalid visual frame bounds')
            if Fraction(last-first, 1)/source_fps != Fraction(out_last-out_first, 1)/fps:
                raise ValueError('Audio handles require unit-rate source correspondence')
            path, _ = _source(cfg, source_row['asset_id'])
            if path['sha256'] != source_row['source_sha256'] or Path(path['path']) != Path(source_row['source_path']).resolve():
                raise ValueError('Visual source mapping changed')
            rows.append(dict(sequence_id=item['id'], asset_id=source_row['asset_id'],
                             source_path=path['path'], source_sha256=path['sha256'],
                             source_first_sample=_sample(Fraction(first, 1)/source_fps),
                             source_end_sample=_sample(Fraction(last, 1)/source_fps),
                             output_first_sample=_sample(Fraction(out_first, 1)/fps),
                             output_end_sample=_sample(Fraction(out_last, 1)/fps)))
    else:
        if plan.get('version') != 3 or not mapping.get('sequence'):
            raise ValueError('Audio handles require an ordered speech mapping')
        fps = 1 / _fraction(str(mapping['xml']['frame_duration']).removesuffix('s'))
        if mapping['sequence_ids'] != [s['id'] for s in plan['sequence']]:
            raise ValueError('Speech sequence and mapping differ')
        identity, _ = _source(cfg)
        if identity != mapping['source'] or identity != plan['source']:
            raise ValueError('Speech source mapping changed')
        if not len(mapping['sequence']) == len(mapping['keep']) == len(plan['sequence']):
            raise ValueError('Speech sequence mapping lengths differ')
        rows = []
        for seq, kept, item in zip(mapping['sequence'], mapping['keep'], plan['sequence']):
            if seq['id'] != item['id'] or abs(seq['source_start']-kept[0]) > 1e-6 or abs(seq['source_end']-kept[1]) > 1e-6:
                raise ValueError('Speech sequence range changed')
            rows.append(dict(sequence_id=seq['id'], source_path=identity['path'], source_sha256=identity['sha256'],
                             source_first_sample=_sample(seq['source_start']), source_end_sample=_sample(seq['source_end']),
                             output_first_sample=_sample(seq['output_start']), output_end_sample=_sample(seq['output_end'])))
    if not rows or rows[0]['output_first_sample'] != 0:
        raise ValueError('Mapping does not begin at zero')
    for index, row in enumerate(rows):
        if row['source_end_sample']-row['source_first_sample'] != row['output_end_sample']-row['output_first_sample']:
            if abs((row['source_end_sample']-row['source_first_sample'])-(row['output_end_sample']-row['output_first_sample'])) > 1:
                raise ValueError('Audio handles require unit-rate sample correspondence')
        if index and row['output_first_sample'] != rows[index-1]['output_end_sample']:
            raise ValueError('Mapping output has a gap or overlap')
    total = rows[-1]['output_end_sample']
    if abs(total-_sample(mapping['duration'])) > 1:
        raise ValueError('Mapping duration changed')
    return rows, fps, total


def _word_occurrences(rows, plan):
    words = plan.get('transcript', {}).get('words', [])
    occurrences = []
    for row in rows:
        for word in words:
            first, last = _sample(word['start']), _sample(word['end'])
            if row['source_first_sample'] < last and first < row['source_end_sample'] and not (
                row['source_first_sample'] <= first and last <= row['source_end_sample']):
                raise ValueError('Mapped baseline contains a partial known word')
            if row['source_first_sample'] <= first and last <= row['source_end_sample']:
                offset = row['output_first_sample']-row['source_first_sample']
                occurrences.append(dict(id=word['id'], text=word['text'], sequence_id=row['sequence_id'],
                                        source_first_sample=first, source_end_sample=last,
                                        output_first_sample=first+offset, output_end_sample=last+offset))
    return occurrences


def _partition(rows, events, total):
    boundaries = {0, total}
    for row in rows:
        boundaries.update((row['output_first_sample'], row['output_end_sample']))
    for event in events:
        boundaries.update((event['output_first_sample'], event['output_end_sample']))
    points = sorted(boundaries)
    result = []
    for start, end in zip(points, points[1:]):
        event = next((e for e in events if e['output_first_sample'] <= start and end <= e['output_end_sample']), None)
        if event:
            source_start = event['source_first_sample'] + start-event['output_first_sample']
            owner = event
        else:
            owner = next(r for r in rows if r['output_first_sample'] <= start and end <= r['output_end_sample'])
            source_start = owner['source_first_sample'] + start-owner['output_first_sample']
        result.append(dict(output_first_sample=start, output_end_sample=end,
                           source_first_sample=source_start, source_end_sample=source_start+end-start,
                           output_start=str(Fraction(start, RATE)), output_end=str(Fraction(end, RATE)),
                           source_start=str(Fraction(source_start, RATE)),
                           source_end=str(Fraction(source_start+end-start, RATE)),
                           source_path=owner['source_path'], source_sha256=owner['source_sha256'],
                           sequence_id=owner['sequence_id'], event_id=event['id'] if event else None))
    return result


def _compile(mapping, plan, cfg, request):
    if not isinstance(request, dict) or set(request) != {'events'} or not isinstance(request['events'], list) or not request['events']:
        raise ValueError('Request needs a nonempty events list')
    rows, fps, total = _rows(mapping, plan, cfg)
    source_durations = {}
    for row in rows:
        if row['source_path'] not in source_durations:
            identity, duration = _source(cfg, row.get('asset_id'))
            if identity['sha256'] != row['source_sha256']:
                raise ValueError('Source changed')
            source_durations[row['source_path']] = _sample(duration)
    original_words = _word_occurrences(rows, plan)
    words = plan.get('transcript', {}).get('words', [])
    events = []
    seen = set()
    for event in request['events']:
        if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
            raise ValueError('Audio event fields differ from the required schema')
        eid = event['id']
        if not isinstance(eid, str) or not eid.strip() or eid in seen:
            raise ValueError('Invalid or repeated audio event id')
        seen.add(eid)
        if event['kind'] not in ('j_cut', 'l_cut') or type(event['duration_frames']) is not int or event['duration_frames'] < 1:
            raise ValueError('Invalid audio event kind or duration')
        if type(event['before_sequence_id']) not in (str,int):
            raise ValueError('Invalid incoming sequence ID')
        if any(not isinstance(event[k], str) or not event[k].strip() for k in ('reason', 'handle_observation', 'replacement_observation')):
            raise ValueError('Audio event needs reason and listening observations')
        for key in ('handle_word_ids', 'repeat_word_ids'):
            if (not isinstance(event[key], list) or any(type(wid) not in (str,int) or (isinstance(wid,str) and not wid) for wid in event[key])
                    or len(event[key]) != len(set(event[key]))):
                raise ValueError('Invalid word ID declaration')
        if event['handle_audio_kind'] not in ('nonspoken','speech'):
            raise ValueError('Declare handle_audio_kind as nonspoken or speech')
        if not words and event['handle_audio_kind'] != 'nonspoken':
            raise ValueError('Speech handles require actual transcript word timings')
        idx = next((i for i, r in enumerate(rows) if r['sequence_id'] == event['before_sequence_id']), None)
        if idx is None or idx == 0:
            raise ValueError('Audio event needs an existing incoming sequence')
        incoming, outgoing = rows[idx], rows[idx-1]
        cut = incoming['output_first_sample']
        if cut != outgoing['output_end_sample']:
            raise ValueError('Audio event boundary changed')
        n = _sample(Fraction(event['duration_frames'], 1)/fps)
        if n <= 0:
            raise ValueError('Audio event is shorter than one sample')
        if event['kind'] == 'j_cut':
            owner, output_start, output_end = incoming, cut-n, cut
            source_start, source_end = incoming['source_first_sample']-n, incoming['source_first_sample']
            if output_start < outgoing['output_first_sample']:
                raise ValueError('J cut exceeds preceding output clip')
            if source_start < 0:
                raise ValueError('J cut exceeds incoming source head')
        else:
            owner, output_start, output_end = outgoing, cut, cut+n
            source_start, source_end = outgoing['source_end_sample'], outgoing['source_end_sample']+n
            if output_end > incoming['output_end_sample']:
                raise ValueError('L cut exceeds following output clip')
        _, handle_duration = _source(cfg, owner.get('asset_id'), require_audio=True)
        if source_end > _sample(handle_duration):
            raise ValueError('Audio handle exceeds source audio track')
        if source_end > source_durations[owner['source_path']]:
            raise ValueError('Audio handle exceeds source audio track')
        if any(output_start < e['output_end_sample'] and e['output_first_sample'] < output_end for e in events):
            raise ValueError('Audio handles overlap')
        if any(output_start < w['output_end_sample'] and w['output_first_sample'] < output_end for w in original_words):
            raise ValueError('Audio override would remove a known audible word')
        for row in rows:
            for protected in plan.get('protected_ranges', []):
                first = max(row['source_first_sample'],_sample(protected['start']))
                end = min(row['source_end_sample'],_sample(protected['end']))
                offset = row['output_first_sample'] - row['source_first_sample']
                if first < end and output_start < end+offset and first+offset < output_end:
                    raise ValueError('Audio override would remove an explicitly protected source interval')
        touching = [w for w in words if source_start < _sample(w['end']) and _sample(w['start']) < source_end]
        if any(not source_start <= _sample(w['start']) < _sample(w['end']) <= source_end for w in touching):
            raise ValueError('Audio handle would include a partial word')
        if words and event['handle_audio_kind'] != ('speech' if touching else 'nonspoken'):
            raise ValueError('Handle audio kind differs from actual transcript words')
        actual_ids = [w['id'] for w in touching]
        if actual_ids != event['handle_word_ids']:
            raise ValueError('Handle word IDs do not match the observed transcript interval')
        repeats = [wid for wid in actual_ids if any(o['id'] == wid for o in original_words) or
                   any(wid in previous['handle_word_ids'] for previous in events)]
        if repeats != event['repeat_word_ids']:
            raise ValueError('Repeated audible words need exact explicit acknowledgment')
        if not words and (event['handle_word_ids'] or event['repeat_word_ids']):
            raise ValueError('Visual handles cannot assert transcript word IDs')
        events.append(dict(id=eid, kind=event['kind'], sequence_id=owner['sequence_id'],
                           output_first_sample=output_start, output_end_sample=output_end,
                           source_first_sample=source_start, source_end_sample=source_end,
                           source_path=owner['source_path'], source_sha256=owner['source_sha256'],
                           handle_word_ids=actual_ids, handle_audio_kind=event['handle_audio_kind'],
                           audio_basis='transcript_word_timings' if words else 'declared_nonspoken_no_ASR'))
    audio_map = _partition(rows, events, total)
    audible = [w for w in original_words if not any(e['output_first_sample'] < w['output_end_sample'] and w['output_first_sample'] < e['output_end_sample'] for e in events)]
    for event in events:
        for word in words:
            first, last = _sample(word['start']), _sample(word['end'])
            if event['source_first_sample'] <= first < last <= event['source_end_sample']:
                offset = event['output_first_sample']-event['source_first_sample']
                audible.append(dict(id=word['id'], text=word['text'], sequence_id=event['sequence_id'],
                                    source_first_sample=first, source_end_sample=last,
                                    output_first_sample=first+offset, output_end_sample=last+offset))
    audible.sort(key=lambda w: (w['output_first_sample'], w['output_end_sample']))
    audible_ids = {word['id'] for word in audible}
    return dict(version=1, fps=str(fps), total_samples=total, events=events,
                audio_map=audio_map, word_occurrences=audible,
                audible_word_ids=[word['id'] for word in words if word['id'] in audible_ids],
                omitted_word_ids=[word['id'] for word in words if word['id'] not in audible_ids])


def prepare_audio_cuts(mapping, plan, cfg, request, actor, reason):
    if actor not in ('human', 'codex', 'claude_code', 'automation') or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Audio-cut decision needs a real actor and reason')
    compiled = _compile(mapping, plan, cfg, request)
    return dict(version=1, input_mapping_sha256=digest(mapping), request=copy.deepcopy(request),
                compiled=compiled, actor=actor, reason=reason)


def verify_audio_cuts(mapping, plan, cfg, setting):
    if (not isinstance(setting, dict) or set(setting) != {'version', 'input_mapping_sha256', 'request', 'compiled', 'actor', 'reason'}
            or type(setting['version']) is not int or setting['version'] != 1):
        raise ValueError('Invalid audio-cut setting')
    if setting['input_mapping_sha256'] != digest(mapping):
        raise ValueError('Audio-cut input mapping changed')
    expected = prepare_audio_cuts(mapping, plan, cfg, setting['request'], setting['actor'], setting['reason'])
    if expected != setting:
        raise ValueError('Audio-cut compilation changed')
    return expected['compiled']


def render_audio_cuts(base_wav, compiled, output_wav):
    """Copy baseline PCM blockwise and splice exact decoded source-handle samples."""
    base_wav, output_wav = Path(base_wav), Path(output_wav)
    if base_wav.resolve() == output_wav.resolve() or output_wav.exists():
        raise ValueError('Output must be a new WAV path')
    events = sorted(compiled['events'], key=lambda e: e['output_first_sample'])
    with wave.open(str(base_wav), 'rb') as baseline:
        if baseline.getframerate() != RATE or baseline.getsampwidth() != 2 or baseline.getcomptype() != 'NONE':
            raise ValueError('Baseline needs uncompressed 48 kHz s16 PCM')
        channels, total = baseline.getnchannels(), baseline.getnframes()
        if total != compiled['total_samples']:
            raise ValueError('Baseline sample count differs from compiled timeline')
        if channels < 1:
            raise ValueError('Invalid baseline channel count')
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_wav.open('xb') as output_file, wave.open(output_file, 'wb') as output:
                output.setparams(baseline.getparams())
                cursor = 0
                for event in events:
                    start, end = event['output_first_sample'], event['output_end_sample']
                    if start < cursor or end > total:
                        raise ValueError('Compiled audio events overlap or exceed baseline')
                    while cursor < start:
                        n = min(65536, start-cursor)
                        chunk = baseline.readframes(n)
                        if len(chunk) != n*channels*2:
                            raise ValueError('Short baseline PCM')
                        output.writeframesraw(chunk)
                        cursor += n
                    identity = fingerprint(event['source_path'])
                    if identity['sha256'] != event['source_sha256']:
                        raise ValueError('Source audio changed before rendering')
                    expected = end-start
                    af = (f'aresample={RATE}:async=1:first_pts=0,'
                          f'atrim=start_sample={event["source_first_sample"]}:end_sample={event["source_end_sample"]},'
                          'asetpts=N/SR/TB')
                    command = ['ffmpeg', '-v', 'error', '-nostdin', '-i', event['source_path'], '-map', '0:a:0',
                               '-vn', '-af', af, '-ar', str(RATE), '-ac', str(channels),
                               '-f', 's16le', '-c:a', 'pcm_s16le', 'pipe:1']
                    decoded = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
                    if len(decoded) != expected*channels*2:
                        raise ValueError('Decoded handle PCM has a short or mismatched sample count')
                    output.writeframesraw(decoded)
                    skipped = baseline.readframes(expected)
                    if len(skipped) != expected*channels*2:
                        raise ValueError('Short baseline PCM')
                    cursor = end
                while cursor < total:
                    n = min(65536, total-cursor)
                    chunk = baseline.readframes(n)
                    if len(chunk) != n*channels*2:
                        raise ValueError('Short baseline PCM')
                    output.writeframesraw(chunk)
                    cursor += n
        except Exception:
            output_wav.unlink(missing_ok=True)
            raise
    return dict(version=1, base=fingerprint(base_wav), output=fingerprint(output_wav),
                total_samples=total, channels=channels, sample_rate=RATE,
                replacements=[{'event_id': e['id'], 'output_first_sample': e['output_first_sample'],
                               'output_end_sample': e['output_end_sample'], 'source_path': e['source_path'],
                               'source_sha256': e['source_sha256'], 'source_first_sample': e['source_first_sample'],
                               'source_end_sample': e['source_end_sample']} for e in events])


def captions_srt(compiled):
    words = compiled['word_occurrences']
    if not words:
        return ''
    from .edl import group_captions, _srt_time
    cues = [{'start':word['output_first_sample']/RATE, 'end':word['output_end_sample']/RATE,
             'text':word['text']} for word in words]
    junctions = [row['output_first_sample']/RATE
                 for previous, row in zip(compiled['audio_map'],compiled['audio_map'][1:])
                 if previous['source_path'] != row['source_path']
                 or previous['source_end_sample'] != row['source_first_sample']]
    groups = group_captions(cues,junctions=junctions)
    return ''.join(f'{index}\n{_srt_time(cue["start"])} --> {_srt_time(cue["end"])}\n{cue["text"]}\n\n'
                   for index, cue in enumerate(groups,1))


def map_audio_output(compiled, start, end):
    first, last = _sample(start), _sample(end)
    if first < 0 or last < first or last > compiled['total_samples']:
        raise ValueError('Inspection interval outside audible timeline')
    spans = []
    for row in compiled['audio_map']:
        lo, hi = max(first, row['output_first_sample']), min(last, row['output_end_sample'])
        if lo < hi:
            source_first = row['source_first_sample'] + lo-row['output_first_sample']
            spans.append(dict(sequence_id=row['sequence_id'], event_id=row['event_id'],
                              source_path=row['source_path'], source_sha256=row['source_sha256'],
                              output_start=lo/RATE, output_end=hi/RATE,
                              source_start=source_first/RATE, source_end=(source_first+hi-lo)/RATE))
    return spans
