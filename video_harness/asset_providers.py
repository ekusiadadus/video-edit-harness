"""Opt-in official provider adapter; transport is injected and no call is automatic."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urlparse
import os
import re

from .patterns import resolve_asset_policy

API_HOST = 'api.pexels.com'
MEDIA_HOSTS = {'images.pexels.com', 'videos.pexels.com', 'player.vimeo.com'}
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
_MIME = {'image/jpeg': '.jpg', 'image/png': '.png', 'video/mp4': '.mp4'}


def official_transport(url, headers):
    """Bounded HTTPS GET without redirects or credential-bearing diagnostics."""
    import json
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from urllib.error import HTTPError, URLError
    _url(url, {API_HOST, *MEDIA_HOSTS})
    api = urlparse(url).hostname == API_HOST
    if not isinstance(headers, dict) or set(headers) - {'Authorization'}:
        raise ValueError('Unsupported provider headers')
    if any(not isinstance(v, str) or '\r' in v or '\n' in v or len(v) > 4096
           for v in headers.values()):
        raise ValueError('Invalid provider credential format')
    if headers and not api:
        raise ValueError('Credentials must never be sent to media hosts')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            return None
    limit = 2 * 1024 * 1024 if api else MAX_DOWNLOAD_BYTES
    try:
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=30) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('Provider response exceeds size limit')
            result = {'status': response.status,
                      'headers': {k.lower(): v for k, v in response.headers.items()}}
            if api:
                if result['headers'].get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ValueError('Expected provider JSON response')
                result['json'] = json.loads(body)
            else:
                result['body'] = body
            return result
    except HTTPError as exc:
        # Do not log response bodies, URLs, keys or authorization headers.
        code = exc.code
        exc.close()
        return {'status': code, 'headers': {}}
    except (URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
        raise ValueError('Provider connection or response failed; local assets remain available') from None


def _guard(policy, api_key, operation):
    parsed = resolve_asset_policy({'asset_policy': policy})
    gate = {'search': 'search_network', 'download': 'download_network'}[operation]
    if parsed[gate] != 'on' or not parsed['destinations']:
        raise ValueError(f'Network asset {operation} is not enabled')
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError('Pexels API key is unavailable')
    return parsed


def _url(url, hosts):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ValueError('Untrusted provider URL')
    return url


def _response(response):
    if not isinstance(response, dict) or type(response.get('status')) is not int or not isinstance(response.get('headers'), dict):
        raise ValueError('Invalid provider response')
    if response['status'] == 429:
        raise ValueError('Pexels rate limit reached; retry later')
    if response['status'] != 200:
        raise ValueError(f"Pexels request failed: HTTP {response['status']}")
    return response


def search_pexels(query: str, kind: str, policy: dict, transport, *, per_page: int = 10) -> list[dict]:
    """Search metadata only; caller controls network and subsequent selection."""
    key = os.environ.get('PEXELS_API_KEY')
    _guard(policy, key, 'search')
    if kind not in {'image', 'video'} or not isinstance(query, str) or not query.strip() or len(query) > 120 or type(per_page) is not int or not 1 <= per_page <= 30:
        raise ValueError('Invalid Pexels search')
    endpoint = 'v1/search' if kind == 'image' else 'v1/videos/search'
    url = _url(f'https://{API_HOST}/{endpoint}?' + urlencode({'query': query, 'per_page': per_page}), {API_HOST})
    response = _response(transport(url, {'Authorization': key}))
    data = response.get('json')
    if not isinstance(data, dict) or not isinstance(data.get('photos' if kind == 'image' else 'videos'), list):
        raise ValueError('Invalid Pexels search payload')
    records = []
    for item in data['photos' if kind == 'image' else 'videos'][:per_page]:
        if not isinstance(item, dict) or not isinstance(item.get('id'), int):
            raise ValueError('Invalid Pexels result')
        page = _url(item.get('url', ''), {'www.pexels.com', 'pexels.com'})
        creator = item.get('photographer' if kind == 'image' else 'user')
        if kind == 'video' and isinstance(creator, dict):
            creator = creator.get('name')
        if not isinstance(creator, str) or not creator.strip():
            raise ValueError('Pexels creator missing')
        media_url = item.get('src', {}).get('original') if kind == 'image' and isinstance(item.get('src'), dict) else None
        if kind == 'video':
            files = item.get('video_files', [])
            media_url = next((f.get('link') for f in files if isinstance(f, dict) and f.get('file_type') == 'video/mp4'), None)
        if media_url is None:
            continue
        _url(media_url, MEDIA_HOSTS)
        records.append({'provider': 'pexels', 'provider_id': item['id'], 'kind': kind,
                        'page_url': page, 'media_url': media_url, 'creator': creator,
                        'attribution': f'{creator} / Pexels ({page})',
                        'rights_status': 'unknown_until_asset_specific_review'})
    return records


def download_pexels(candidate: dict, folder, policy: dict, transport, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> Path:
    """Bounded save of a selected result; never claims rights verification."""
    key = os.environ.get('PEXELS_API_KEY')
    _guard(policy, key, 'download')
    if candidate.get('provider') != 'pexels' or candidate.get('kind') not in {'image', 'video'} or type(candidate.get('provider_id')) is not int:
        raise ValueError('Invalid Pexels candidate')
    _url(candidate.get('page_url', ''), {'www.pexels.com', 'pexels.com'})
    url = _url(candidate.get('media_url', ''), MEDIA_HOSTS)
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_DOWNLOAD_BYTES:
        raise ValueError('Invalid download size limit')
    response = _response(transport(url, {}))
    mime = response['headers'].get('content-type', '').split(';', 1)[0].strip().lower()
    if mime not in _MIME or (candidate['kind'] == 'video') != (mime == 'video/mp4'):
        raise ValueError('Unexpected Pexels media type')
    body = response.get('body')
    if not isinstance(body, bytes) or not 0 < len(body) <= max_bytes:
        raise ValueError('Pexels media exceeds size limit or is empty')
    declared = response['headers'].get('content-length')
    if declared is not None and (not re.fullmatch(r'\d+', str(declared)) or int(declared) != len(body)):
        raise ValueError('Pexels length mismatch')
    if mime == 'image/jpeg' and not body.startswith(b'\xff\xd8\xff') or mime == 'image/png' and not body.startswith(b'\x89PNG\r\n\x1a\n') or mime == 'video/mp4' and body[4:8] != b'ftyp':
        raise ValueError('Pexels payload does not match MIME')
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pexels-{candidate['provider_id']}{_MIME[mime]}"
    with path.open('xb') as stream:
        stream.write(body)
    return path


def manual_import_only(provider: str) -> None:
    if provider not in {'youtube_audio_library', 'mixkit', 'pixabay', 'otologic', 'opentracks', 'tiktok_cml'}:
        raise ValueError('Unknown manual provider')
    raise ValueError(f'{provider} supports manual local registration only')
