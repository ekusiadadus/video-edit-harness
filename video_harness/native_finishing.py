"""Local native-finishing proposals and returned-media inspection; no upload."""
from copy import deepcopy
from fractions import Fraction
from urllib.parse import urlparse

import math
from pathlib import Path
import re
import json

from .common import fingerprint, run, write


def _url(value):
    if not isinstance(value, str):
        raise ValueError('Native selection needs an official TikTok reference URL')
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or parsed.hostname not in {'www.tiktok.com', 'tiktok.com',
            'ads.tiktok.com', 'effecthouse.tiktok.com', 'effecthouse.us.tiktok.com'}
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError('Native selection needs an official TikTok reference URL')
    return value


def _time(value):
    try:
        if isinstance(value, bool):
            raise ValueError()
        return Fraction(str(value).removesuffix('s'))
    except (ValueError, ZeroDivisionError):
        raise ValueError('Invalid native finishing time') from None


def plan_native_finishing(video, mapping, production, request):
    """Seal references and timing proposals without asserting availability or rights."""
    if not isinstance(request, dict) or set(request) - {'platform', 'usage', 'region', 'music', 'effects'}:
        raise ValueError('Invalid native finishing request')
    if request.get('platform') != 'tiktok' or request.get('usage') not in {'personal', 'commercial'}:
        raise ValueError('Native finishing currently supports explicit TikTok usage only')
    region = request.get('region')
    if not isinstance(region, str) or len(region) != 2 or not region.isupper() or not region.isalpha():
        raise ValueError('Native finishing requires a region')
    if fingerprint(video['path']) != video:
        raise ValueError('Native finishing base video changed')
    duration = _time(mapping['duration'])
    music = request.get('music')
    if music is not None:
        if not isinstance(music, dict) or set(music) != {'reference_url', 'start_offset', 'library'}:
            raise ValueError('Native music needs reference_url, start_offset and library')
        _url(music['reference_url'])
        if music['library'] not in {'cml', 'general'} or _time(music['start_offset']) < 0:
            raise ValueError('Invalid native music library or offset')
        if request['usage'] == 'commercial' and music['library'] != 'cml':
            raise ValueError('Commercial native music requires CML selection or separately cleared local audio')
    if any(cue['role'] == 'music' for cue in production.get('cues', [])):
        raise ValueError('Use a base without baked-in BGM before native music selection')
    effects = request.get('effects', [])
    if not isinstance(effects, list):
        raise ValueError('Native effects must be a list')
    seen = set()
    for effect in effects:
        if (not isinstance(effect, dict) or set(effect) != {'id', 'reference_url', 'start', 'end', 'reason'}
                or not isinstance(effect['id'], str) or not effect['id'] or effect['id'] in seen
                or not isinstance(effect['reason'], str) or not effect['reason'].strip()):
            raise ValueError('Invalid native effect request')
        _url(effect['reference_url'])
        if not 0 <= _time(effect['start']) < _time(effect['end']) <= duration:
            raise ValueError('Native effect outside base video')
        seen.add(effect['id'])
    return {'version': 1, 'status': 'awaiting_native_editor_selection_and_review',
            'platform': 'tiktok', 'usage': request['usage'], 'region': region,
            'base_video': deepcopy(video), 'duration': str(duration),
            'music': deepcopy(music), 'effects': deepcopy(effects),
            'native_music_applied': False, 'native_effects_applied': False,
            'uploaded': False, 'published': False, 'cross_platform_rights_verified': False,
            'beat_sync': 'Recheck cuts against the selected native track and start offset; prior beat grid does not prove sync.',
            'required_checks': ['Track availability for the selected region and commercial placement',
                                'Effect supports this uploaded video rather than capture only',
                                'Selected sound start offset, cut alignment and original sound volume',
                                'Native preview visual/listening review and explicit upload/publication approval']}


def validate_native_receipt(proposal, returned_video, receipt):
    """Check an explicit source/output declaration, not the truth of native execution."""
    fields = {'base_video_sha256', 'result_video_sha256', 'method', 'reference_url',
              'reported_music_applied', 'reported_effect_ids', 'note'}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise ValueError('Native result needs an exact source/output receipt')
    if (receipt['base_video_sha256'] != proposal['base_video']['sha256']
            or receipt['result_video_sha256'] != returned_video['sha256']):
        raise ValueError('Native result receipt source/output SHA mismatch')
    if receipt['method'] not in {'studio_ui', 'business_api', 'symphony_api'}:
        raise ValueError('Unknown native finishing method')
    _url(receipt['reference_url'])
    # OAuth callback URLs and tokens must never become local editing artifacts.
    from urllib.parse import parse_qs
    query = parse_qs(urlparse(receipt['reference_url']).query, keep_blank_values=True)
    if set(query) - {'tempId'}:
        raise ValueError('Native receipt URL must not contain authentication or other query parameters')
    if type(receipt['reported_music_applied']) is not bool:
        raise ValueError('Native music report must be a boolean')
    if receipt['reported_music_applied'] and proposal['music'] is None:
        raise ValueError('Reported native music differs from the proposal')
    ids = receipt['reported_effect_ids']
    if (not isinstance(ids, list) or any(not isinstance(value, str) for value in ids)
            or len(ids) != len(set(ids))
            or set(ids) - {effect['id'] for effect in proposal['effects']}):
        raise ValueError('Reported native effects differ from the proposal')
    if not isinstance(receipt['note'], str) or not receipt['note'].strip():
        raise ValueError('Native result receipt needs an observation note')
    return deepcopy(receipt)


def inspect_native_result(video, output, require_music=False):
    """Decode a returned file and flag absent/near-silent audio without approving music."""
    if type(require_music) is not bool:
        raise ValueError('require_music must be a boolean')
    video = Path(video).resolve()
    original = fingerprint(video)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # A downloaded MP4 must not be interpreted as a network playlist.
    input_args = ['-protocol_whitelist', 'file,pipe', '-f', 'mov', '-i', str(video)]
    probe_log = run(['ffprobe', '-v', 'error', *input_args, '-show_streams', '-show_format',
                     '-of', 'json'], output / 'probe.log')
    data = json.loads(probe_log.split('\n', 1)[1])
    write(output / 'probe.json', data)
    picture = next((stream for stream in data['streams'] if stream['codec_type'] == 'video'), None)
    if picture is None:
        raise ValueError('Native result has no video stream')
    duration = float(data['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Native result has invalid duration')
    run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-xerror', *input_args,
         '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], output / 'decode.log')
    audio = next((stream for stream in data['streams'] if stream['codec_type'] == 'audio'), None)
    measurement = {'audio_stream_present': audio is not None, 'peak_db': None,
                   'near_silent': None, 'near_silent_threshold_db': -90,
                   'scope': 'first audio stream, whole file; not track identity or listening review'}
    if audio is not None:
        log = run(['ffmpeg', '-hide_banner', '-nostdin', *input_args, '-map', '0:a:0',
                   '-vn', '-af', 'volumedetect', '-f', 'null', '-'], output / 'audio-level.log')
        match = re.search(r'max_volume:\s*(-?inf|[-+\d.]+) dB', log)
        if not match:
            raise ValueError('Cannot establish native result audio level')
        peak = float(match.group(1))
        if math.isnan(peak) or peak == math.inf:
            raise ValueError('Invalid native result audio level')
        measurement.update(peak_db=peak if math.isfinite(peak) else None,
                           near_silent=peak <= measurement['near_silent_threshold_db'])
    write(output / 'audio-measurement.json', measurement)
    if fingerprint(video) != original:
        raise ValueError('Native result changed during inspection')
    missing_music = require_music and (audio is None or measurement['near_silent'])
    result = {'version': 1, 'video': original, 'decode': 'pass', 'duration': duration,
              'picture': {'width': picture['width'], 'height': picture['height'],
                          'frame_rate': picture.get('avg_frame_rate'),
                          'declared_frame_count': picture.get('nb_frames')},
              'audio': measurement, 'music_requested': require_music,
              'status': 'requested_music_not_demonstrated' if missing_music else 'awaiting_native_result_review',
              'music_identity_verified': False, 'native_effects_verified': False,
              'source_relationship_verified': False, 'timeline_mapping_inherited': False,
              'human_visual_review': False, 'human_listening_review': False,
              'cross_platform_rights_verified': False, 'published': False,
              'next_action': ('Return to the native editor: requested music is absent or near-silent.'
                              if missing_music else
                              'Verify source relationship, selected music/effects, rights and exact-file playback.'),
              'evidence': {name: fingerprint(output / name) for name in
                           ('probe.json', 'probe.log', 'decode.log', 'audio-measurement.json') +
                           (('audio-level.log',) if audio is not None else ())}}
    write(output / 'inspection.json', result)
    return result
