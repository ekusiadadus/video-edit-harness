"""Local instructions for platform-native finishing; no upload or native render."""
from copy import deepcopy
from fractions import Fraction
from urllib.parse import urlparse

from .common import fingerprint


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
