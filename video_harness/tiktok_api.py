"""Bounded, read-only TikTok Login Kit and Display API client.

The only network writes here are OAuth code exchange and token refresh. They
never upload media or publish a post. Secrets and callback codes are never
returned in public results.
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from http.server import BaseHTTPRequestHandler, HTTPServer


AUTH_URL = 'https://www.tiktok.com/v2/auth/authorize/'
API_ORIGIN = 'https://open.tiktokapis.com'
SCOPES = ('user.info.basic', 'video.list')
MAX_RESPONSE = 1024 * 1024
SERVICE = 'video-edit-harness.tiktok'


class TikTokAPIError(ValueError):
    """Intentionally free of token, code and server-provided message text."""


def _config(keychain=None):
    key = os.environ.get('TIKTOK_CLIENT_KEY', '')
    secret = os.environ.get('TIKTOK_CLIENT_SECRET', '')
    redirect = os.environ.get('TIKTOK_REDIRECT_URI', '')
    if not all((key, secret, redirect)):
        raw = (keychain if keychain is not None else Keychain()).get('config')
        if raw:
            try:
                saved = json.loads(raw)
                key = key or saved['client_key']
                secret = secret or saved['client_secret']
                redirect = redirect or saved['redirect_uri']
            except (ValueError, KeyError, TypeError):
                raise TikTokAPIError('Stored TikTok configuration is invalid') from None
    if not key or not secret or not redirect:
        raise TikTokAPIError('TikTok client key, secret and redirect URI must be configured')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,128}', key):
        raise TikTokAPIError('Invalid TikTok client key format')
    _redirect(redirect)
    return key, secret, redirect


def _redirect(uri):
    try:
        parsed = urlparse(uri)
        port = parsed.port
    except ValueError:
        raise TikTokAPIError('Desktop redirect must be a registered, static loopback URI with a port') from None
    if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'localhost', '127.0.0.1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or port is None or not 1 <= port <= 65535 or len(uri) >= 512):
        raise TikTokAPIError('Desktop redirect must be a registered, static loopback URI with a port')
    return uri


class Keychain:
    """macOS Keychain, with encoded password supplied to security -i on stdin."""

    def __init__(self, client_key=None):
        if sys.platform != 'darwin':
            raise TikTokAPIError('macOS Keychain is required for TikTok credential storage')
        self.service = (SERVICE + '.config' if client_key is None else
            SERVICE + '.' + hashlib.sha256(client_key.encode()).hexdigest()[:16])

    def set(self, account, value):
        if account not in {'config', 'pending', 'tokens'}:
            raise TikTokAPIError('Invalid Keychain account')
        encoded = base64.urlsafe_b64encode(value.encode()).decode()
        script = f'add-generic-password -U -a {account} -s {self.service} -w {encoded}\n'
        try:
            subprocess.run(['security', '-i'], input=script, text=True,
                           capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise TikTokAPIError('Keychain write failed') from None
        if self.get(account) != value:
            raise TikTokAPIError('Keychain write failed')

    def get(self, account):
        try:
            proc = subprocess.run(['security', 'find-generic-password', '-a', account,
                                   '-s', self.service, '-w'], capture_output=True,
                                  text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise TikTokAPIError('Keychain read failed') from None
        if proc.returncode:
            return None
        try:
            return base64.b64decode(proc.stdout.strip(), altchars=b'-_', validate=True).decode()
        except (ValueError, UnicodeError):
            raise TikTokAPIError('Stored Keychain value is invalid') from None


def configure(client_key, client_secret, redirect_uri, *, keychain=None):
    if not isinstance(client_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,128}', client_key):
        raise TikTokAPIError('Invalid TikTok client key format')
    if not isinstance(client_secret, str) or not client_secret or len(client_secret) > 2048:
        raise TikTokAPIError('Invalid TikTok client secret')
    _redirect(redirect_uri)
    storage = keychain if keychain is not None else Keychain()
    storage.set('config', json.dumps({'client_key': client_key,
        'client_secret': client_secret, 'redirect_uri': redirect_uri}))
    return {'configured': True, 'redirect_uri': redirect_uri}


def _store(client_key, keychain=None):
    return keychain if keychain is not None else Keychain(client_key)


def auth_url(*, scopes=SCOPES, keychain=None):
    key, _, redirect = _config(keychain)
    if (not isinstance(scopes, (list, tuple)) or not scopes or
            any(scope not in SCOPES for scope in scopes) or len(set(scopes)) != len(scopes)):
        raise TikTokAPIError('Unsupported TikTok OAuth scope request')
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = hashlib.sha256(verifier.encode('ascii')).hexdigest()  # TikTok Desktop uses hex.
    _store(key, keychain).set('pending', json.dumps({'state': state, 'verifier': verifier,
        'redirect': redirect, 'created': int(time.time()), 'scopes': list(scopes)}))
    query = urlencode({'client_key': key, 'response_type': 'code', 'scope': ','.join(scopes),
                       'redirect_uri': redirect, 'state': state,
                       'code_challenge': challenge, 'code_challenge_method': 'S256'})
    return {'authorize_url': AUTH_URL + '?' + query, 'scopes': list(scopes),
            'expires_in_seconds': 600}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise TikTokAPIError('TikTok API redirect refused')


def _request(path, *, method, token=None, form=None, payload=None, transport=None):
    if path not in {'/v2/oauth/token/', '/v2/user/info/', '/v2/video/list/'}:
        raise TikTokAPIError('Unsupported TikTok API endpoint')
    url = API_ORIGIN + path
    if path == '/v2/user/info/':
        url += '?fields=open_id,display_name,avatar_url'
    if path == '/v2/video/list/':
        url += '?fields=id,title,create_time,share_url'
    body = urlencode(form).encode() if form is not None else (json.dumps(payload).encode() if payload is not None else None)
    headers = {'Accept': 'application/json'}
    if form is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(url, data=body, headers=headers, method=method)
    try:
        if transport is None:
            response = build_opener(_NoRedirect()).open(req, timeout=10)
        else:
            response = transport(req, timeout=10)
        with response:
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
        if status != 200 or len(raw) > MAX_RESPONSE:
            raise TikTokAPIError('TikTok API response status or size invalid')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise TikTokAPIError('TikTok API response shape invalid')
        error = result.get('error')
        if isinstance(error, dict) and error.get('code') not in (None, 'ok'):
            raise TikTokAPIError('TikTok API refused the request')
        if isinstance(error, str):
            raise TikTokAPIError('TikTok API refused the request')
        return result
    except TikTokAPIError:
        raise
    except (OSError, ValueError, UnicodeError) as exc:
        raise TikTokAPIError('TikTok API request failed') from None


def _token_receipt(data):
    required = ('access_token', 'refresh_token', 'open_id', 'scope', 'expires_in', 'refresh_expires_in')
    if (any(not isinstance(data.get(key), str) or not data[key] for key in required[:4])
            or data.get('token_type') != 'Bearer'):
        raise TikTokAPIError('TikTok token response incomplete')
    if not isinstance(data['expires_in'], int) or not isinstance(data['refresh_expires_in'], int):
        raise TikTokAPIError('TikTok token lifetime invalid')
    if not 0 < data['expires_in'] <= 7 * 86400 or not 0 < data['refresh_expires_in'] <= 2 * 366 * 86400:
        raise TikTokAPIError('TikTok token lifetime invalid')
    return {'open_id': data['open_id'], 'scopes': data['scope'].split(','),
            'access_expires_at': int(time.time()) + data['expires_in'],
            'refresh_expires_at': int(time.time()) + data['refresh_expires_in']}


def exchange(callback_url, *, keychain=None, transport=None):
    key, secret, redirect = _config(keychain)
    storage = _store(key, keychain)
    pending_text = storage.get('pending')
    if not pending_text:
        raise TikTokAPIError('No pending TikTok authorization')
    try:
        pending = json.loads(pending_text)
        callback = urlparse(callback_url)
        expected = urlparse(redirect)
        values = parse_qs(callback.query, strict_parsing=True)
        if (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path):
            raise ValueError()
        if callback.fragment or set(values) - {'code', 'state', 'scopes'} or any(len(v) != 1 for v in values.values()):
            raise ValueError()
        if not secrets.compare_digest(values['state'][0], pending['state']):
            raise ValueError()
        if pending['redirect'] != redirect or not 0 <= time.time() - pending['created'] <= 600:
            raise ValueError()
        code = values['code'][0]
        if not code or len(code) > 2048:
            raise ValueError()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise TikTokAPIError('TikTok callback state, origin or age invalid') from None
    data = _request('/v2/oauth/token/', method='POST', form={
        'client_key': key, 'client_secret': secret, 'code': code,
        'grant_type': 'authorization_code', 'redirect_uri': redirect,
        'code_verifier': pending['verifier']}, transport=transport)
    receipt = _token_receipt(data)
    storage.set('tokens', json.dumps({**receipt, 'access_token': data['access_token'],
                                     'refresh_token': data['refresh_token']}))
    storage.set('pending', '{}')
    return receipt


def connect(*, scopes=SCOPES, keychain=None, transport=None, on_url=None, timeout=600):
    """Listen on the registered loopback callback and exchange one valid code."""
    key, _, redirect = _config(keychain)
    target = urlparse(redirect)
    if target.hostname != '127.0.0.1':
        raise TikTokAPIError('Automatic callback listener requires 127.0.0.1 redirect')
    if type(timeout) not in (int, float) or not 0 < timeout <= 600:
        raise TikTokAPIError('Invalid TikTok callback timeout')
    received = []
    storage = _store(key, keychain)

    class CallbackHandler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass  # Never log the callback path, which contains the code.

        def do_GET(self):
            request = urlparse(self.path)
            valid = False
            if len(self.path) <= 4096 and request.path == target.path and not request.fragment:
                try:
                    values = parse_qs(request.query, strict_parsing=True)
                    pending = json.loads(storage.get('pending') or '{}')
                    valid = (set(values) <= {'code', 'state', 'scopes'} and
                             all(len(v) == 1 for v in values.values()) and
                             bool(values.get('code', [''])[0]) and
                             secrets.compare_digest(values['state'][0], pending['state']))
                except (ValueError, KeyError, TypeError):
                    valid = False
            if valid:
                received.append(redirect + '?' + request.query)
            try:
                self.send_response(200 if valid else 400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write((b'Authorization received; return to terminal.' if valid else
                                  b'Invalid authorization callback.'))
            except (BrokenPipeError, ConnectionResetError):
                pass

    class LoopbackServer(HTTPServer):
        allow_reuse_address = False

        def handle_error(self, *_args):
            pass  # Callback request paths and codes must never reach stderr.

    try:
        server = LoopbackServer(('127.0.0.1', target.port), CallbackHandler)
    except OSError:
        raise TikTokAPIError('Registered TikTok callback port is unavailable') from None
    try:
        authorization = auth_url(scopes=scopes, keychain=keychain)
        if on_url is not None:
            on_url(authorization)
        deadline = time.monotonic() + timeout
        while not received and time.monotonic() < deadline:
            server.timeout = min(1, max(0.01, deadline - time.monotonic()))
            server.handle_request()
        if not received:
            raise TikTokAPIError('TikTok authorization callback timed out')
    finally:
        server.server_close()
    return exchange(received[0], keychain=keychain, transport=transport)


def _tokens(keychain=None):
    key, secret, _ = _config(keychain)
    raw = _store(key, keychain).get('tokens')
    if not raw:
        raise TikTokAPIError('TikTok authorization is not connected')
    try:
        data = json.loads(raw)
        if not data['access_token'] or not data['refresh_token']:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise TikTokAPIError('Stored TikTok authorization is invalid') from None
    return key, secret, data


def refresh(*, keychain=None, transport=None):
    key, secret, old = _tokens(keychain)
    if old['refresh_expires_at'] <= time.time():
        raise TikTokAPIError('TikTok refresh authorization expired')
    data = _request('/v2/oauth/token/', method='POST', form={
        'client_key': key, 'client_secret': secret, 'grant_type': 'refresh_token',
        'refresh_token': old['refresh_token']}, transport=transport)
    receipt = _token_receipt(data)
    _store(key, keychain).set('tokens', json.dumps({**receipt,
        'access_token': data['access_token'], 'refresh_token': data['refresh_token']}))
    return receipt


def status(*, keychain=None):
    configured = {name: bool(os.environ.get(name)) for name in
                  ('TIKTOK_CLIENT_KEY', 'TIKTOK_CLIENT_SECRET', 'TIKTOK_REDIRECT_URI')}
    result = {'configured': configured, 'connected': False, 'keychain_configured': False}
    raw_config = (keychain if keychain is not None else Keychain()).get('config')
    if raw_config:
        result['keychain_configured'] = True
    if not all(configured.values()) and not raw_config:
        return result
    key, _, _ = _config(keychain)
    raw = _store(key, keychain).get('tokens')
    if raw:
        try:
            data = json.loads(raw)
            result.update(connected=True, scopes=data['scopes'],
                          access_expires_at=data['access_expires_at'],
                          refresh_expires_at=data['refresh_expires_at'])
        except (ValueError, KeyError, TypeError):
            raise TikTokAPIError('Stored TikTok authorization is invalid') from None
    return result


connection_status = status


def _authorized(scope, keychain=None):
    _, _, data = _tokens(keychain)
    if scope not in data['scopes']:
        raise TikTokAPIError('TikTok scope was not granted')
    if data['access_expires_at'] <= time.time():
        raise TikTokAPIError('TikTok access token expired; refresh explicitly')
    return data['access_token']


def profile(*, keychain=None, transport=None):
    token = _authorized('user.info.basic', keychain)
    result = _request('/v2/user/info/', method='GET', token=token, transport=transport)
    user = result.get('data', {}).get('user')
    if not isinstance(user, dict) or not isinstance(user.get('open_id'), str):
        raise TikTokAPIError('TikTok profile response invalid')
    return {key: user[key] for key in ('open_id', 'display_name', 'avatar_url') if key in user}


def videos(*, max_count=10, cursor=None, keychain=None, transport=None):
    if type(max_count) is not int or not 1 <= max_count <= 20 or (cursor is not None and
            (type(cursor) is not int or cursor < 0)):
        raise TikTokAPIError('Invalid TikTok video page request')
    token = _authorized('video.list', keychain)
    payload = {'max_count': max_count}
    if cursor is not None:
        payload['cursor'] = cursor
    result = _request('/v2/video/list/', method='POST', token=token,
                      payload=payload, transport=transport)
    data = result.get('data', {})
    if not isinstance(data, dict) or not isinstance(data.get('videos'), list) or type(data.get('has_more')) is not bool:
        raise TikTokAPIError('TikTok video list response invalid')
    return {'videos': [{key: item[key] for key in ('id', 'title', 'create_time', 'share_url')
                       if key in item} for item in data['videos'] if isinstance(item, dict)],
            'cursor': data.get('cursor'), 'has_more': data['has_more']}
