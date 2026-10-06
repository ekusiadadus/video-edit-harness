import io
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from video_harness import tiktok_api as api
from video_harness.tiktok_cli import main as cli_main


class MemoryKeychain:
    def __init__(self):
        self.values = {}

    def set(self, account, value):
        self.values[account] = value

    def get(self, account):
        return self.values.get(account)


class Response:
    status = 200

    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, limit):
        return self.data[:limit]


class TikTokAPITests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TIKTOK_CLIENT_KEY': 'fixture_key',
                                           'TIKTOK_CLIENT_SECRET': 'private_secret',
                                           'TIKTOK_REDIRECT_URI': 'http://127.0.0.1:3455/callback/'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.storage = MemoryKeychain()

    def token_response(self, access='secret_access', refresh='secret_refresh'):
        return {'access_token': access, 'refresh_token': refresh, 'open_id': 'person-1',
                'scope': 'user.info.basic,video.list', 'token_type': 'Bearer',
                'expires_in': 3600, 'refresh_expires_in': 86400}

    def connected(self):
        auth = api.auth_url(keychain=self.storage)
        state = parse_qs(urlparse(auth['authorize_url']).query)['state'][0]
        callback = os.environ['TIKTOK_REDIRECT_URI'] + '?' + urlencode({'code': 'code-secret', 'state': state})
        seen = []

        def transport(req, timeout):
            seen.append((req, timeout))
            return Response(self.token_response())

        receipt = api.exchange(callback, keychain=self.storage, transport=transport)
        return auth, receipt, seen

    def test_desktop_pkce_state_exchange_and_no_token_receipt(self):
        auth, receipt, seen = self.connected()
        query = parse_qs(urlparse(auth['authorize_url']).query)
        self.assertEqual(urlparse(auth['authorize_url']).netloc, 'www.tiktok.com')
        self.assertEqual(query['scope'], ['user.info.basic,video.list'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(len(query['code_challenge'][0]), 64)
        self.assertEqual(seen[0][0].full_url, api.API_ORIGIN + '/v2/oauth/token/')
        self.assertIn(b'code_verifier=', seen[0][0].data)
        self.assertNotIn('access_token', receipt)
        self.assertNotIn('refresh_token', receipt)
        self.assertEqual(api.status(keychain=self.storage)['scopes'], list(api.SCOPES))
        self.assertEqual(json.loads(self.storage.get('tokens'))['access_token'], 'secret_access')

    def test_callback_state_origin_expiry_and_redirect_rejected_before_network(self):
        auth = api.auth_url(keychain=self.storage)
        state = parse_qs(urlparse(auth['authorize_url']).query)['state'][0]
        callbacks = ['http://evil.example/callback/?code=x&state=' + state,
                     os.environ['TIKTOK_REDIRECT_URI'] + '?code=x&state=wrong',
                     os.environ['TIKTOK_REDIRECT_URI'] + '?code=x&state=' + state + '&extra=1']
        for callback in callbacks:
            with self.subTest(callback=callback):
                with self.assertRaisesRegex(api.TikTokAPIError, 'callback state'):
                    api.exchange(callback, keychain=self.storage,
                                 transport=lambda *_args, **_kwargs: self.fail('network'))
        pending = json.loads(self.storage.get('pending'))
        pending['created'] = 1
        self.storage.set('pending', json.dumps(pending))
        with self.assertRaisesRegex(api.TikTokAPIError, 'callback state'):
            api.exchange(os.environ['TIKTOK_REDIRECT_URI'] + '?code=x&state=' + state,
                         keychain=self.storage)
        with patch.dict(os.environ, {'TIKTOK_REDIRECT_URI': 'https://example.com/callback/'}):
            with self.assertRaisesRegex(api.TikTokAPIError, 'loopback'):
                api.auth_url(keychain=self.storage)

    def test_refresh_profile_videos_and_scope_gate(self):
        self.connected()
        seen = []

        def transport(req, timeout):
            seen.append(req)
            if req.full_url.endswith('/v2/oauth/token/'):
                return Response(self.token_response('new_access', 'new_refresh'))
            if '/v2/user/info/' in req.full_url:
                return Response({'data': {'user': {'open_id': 'person-1',
                    'display_name': 'Fixture', 'avatar_url': 'https://example.org/a'}} ,
                    'error': {'code': 'ok'}})
            return Response({'data': {'videos': [{'id': '123', 'title': 'Fixture'}],
                        'cursor': 123, 'has_more': False}, 'error': {'code': 'ok'}})

        refreshed = api.refresh(keychain=self.storage, transport=transport)
        self.assertNotIn('access_token', refreshed)
        self.assertEqual(json.loads(self.storage.get('tokens'))['refresh_token'], 'new_refresh')
        self.assertEqual(api.profile(keychain=self.storage, transport=transport)['display_name'], 'Fixture')
        self.assertEqual(api.videos(max_count=20, cursor=123, keychain=self.storage,
                                    transport=transport)['videos'][0]['id'], '123')
        self.assertEqual(seen[-1].get_method(), 'POST')
        self.assertIn(b'"max_count": 20', seen[-1].data)
        with self.assertRaisesRegex(api.TikTokAPIError, 'Invalid TikTok video'):
            api.videos(max_count=21, keychain=self.storage)
        stored = json.loads(self.storage.get('tokens'))
        stored['scopes'] = ['user.info.basic']
        self.storage.set('tokens', json.dumps(stored))
        with self.assertRaisesRegex(api.TikTokAPIError, 'scope'):
            api.videos(keychain=self.storage, transport=transport)

    def test_cli_requires_network_and_never_echoes_credentials(self):
        with patch('sys.stdout', new_callable=io.StringIO) as stdout:
            with patch('video_harness.tiktok_api.Keychain', return_value=self.storage):
                cli_main(['status'])
            self.assertNotIn('private_secret', stdout.getvalue())
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                cli_main(['profile'])
            self.assertIn('--network', stderr.getvalue())

    def test_keychain_config_and_single_scope_loopback_callback(self):
        storage = MemoryKeychain()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        redirect = f'http://127.0.0.1:{port}/callback'
        with patch.dict(os.environ, {'TIKTOK_CLIENT_KEY': '', 'TIKTOK_CLIENT_SECRET': '',
                                     'TIKTOK_REDIRECT_URI': ''}):
            safe = api.configure('fixture_key', 'private_secret', redirect, keychain=storage)
            self.assertNotIn('private_secret', str(safe))
            self.assertTrue(api.status(keychain=storage)['keychain_configured'])
            responses = []
            visitors = []
            browser_errors = []

            def browser(auth):
                state = parse_qs(urlparse(auth['authorize_url']).query)['state'][0]

                def visit():
                    try:
                        try:
                            urlopen(redirect + '?code=wrong&state=bad', timeout=3)
                        except Exception:
                            pass
                        with urlopen(redirect + '?code=fixture-code&state=' + state, timeout=3) as response:
                            responses.append(response.status)
                    except Exception as exc:
                        browser_errors.append(type(exc).__name__)

                visitor = threading.Thread(target=visit)
                visitors.append(visitor)
                visitor.start()

            receipt = api.connect(scopes=('user.info.basic',), keychain=storage,
                transport=lambda req, timeout: Response({**self.token_response(),
                    'scope': 'user.info.basic'}), on_url=browser, timeout=5)
            visitors[0].join(timeout=4)
            self.assertFalse(visitors[0].is_alive(), 'callback client did not finish')
            self.assertEqual(browser_errors, [])
            self.assertEqual(receipt['scopes'], ['user.info.basic'])
            self.assertEqual(responses, [200])

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS Keychain only')
    def test_real_isolated_keychain_roundtrip_without_secret_argv(self):
        name = 'fixture_' + secrets.token_hex(8)
        storage = api.Keychain(name)
        value = json.dumps({'generated': secrets.token_urlsafe(24), 'quote': '"'})
        try:
            storage.set('pending', value)
            self.assertEqual(storage.get('pending'), value)
        finally:
            subprocess.run(['security', 'delete-generic-password', '-a', 'pending',
                            '-s', storage.service], capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
