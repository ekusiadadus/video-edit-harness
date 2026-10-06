import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_harness.asset_providers import search_pexels, download_pexels, manual_import_only, official_transport

POLICY = {'destinations': ['youtube'], 'search_network': 'on', 'download_network': 'on'}


class PexelsTests(unittest.TestCase):
    def test_current_video_endpoint_and_credit(self):
        calls = []
        def transport(url, headers):
            calls.append(url)
            return {'status': 200, 'headers': {}, 'json': {'videos': [{
                'id': 7, 'url': 'https://www.pexels.com/video/7/',
                'user': {'name': 'Artist'}, 'video_files': [{'file_type': 'video/mp4',
                'link': 'https://videos.pexels.com/video-files/7/test.mp4'}]}]}}
        with patch.dict(os.environ, {'PEXELS_API_KEY': 'test'}):
            result = search_pexels('mountain', 'video', POLICY, transport)
        self.assertIn('/v1/videos/search?', calls[0])
        self.assertIn('Pexels', result[0]['attribution'])

    def test_transport_bounds_and_does_not_forward_credentials(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status = 200
        response.headers = {'Content-Type': 'application/json'}
        response.read.return_value = b'{"photos": []}'
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch('urllib.request.build_opener', return_value=opener) as factory:
            result = official_transport('https://api.pexels.com/v1/search?query=test', {'Authorization': 'test'})
            self.assertEqual(result['json'], {'photos': []})
            self.assertIsNone(factory.call_args.args[0].redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))
            self.assertEqual(response.read.call_args.args[0], 2 * 1024 * 1024 + 1)
            response.read.return_value = b'x' * (2 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(ValueError, 'size limit'):
                official_transport('https://api.pexels.com/v1/search', {})
        with self.assertRaisesRegex(ValueError, 'Credentials'):
            official_transport('https://images.pexels.com/test.jpg', {'Authorization': 'test'})

    def test_search_injected_transport_and_separate_permission(self):
        calls = []
        def transport(url, headers):
            calls.append((url, headers))
            return {'status': 200, 'headers': {}, 'json': {'photos': [{
                'id': 42, 'url': 'https://www.pexels.com/photo/42/', 'photographer': 'Artist',
                'src': {'original': 'https://images.pexels.com/photos/42/photo.jpg'}}]}}
        with patch.dict(os.environ, {'PEXELS_API_KEY': 'test'}):
            with self.assertRaises(ValueError):
                search_pexels('mountain', 'image', {'destinations': ['youtube'], 'download_network': 'on'}, transport)
            found = search_pexels('mountain', 'image', POLICY, transport)
            self.assertTrue(found[0]['rights_status'].startswith('unknown'))
            self.assertIn('/v1/search?', calls[0][0])
            self.assertEqual(calls[0][1], {'Authorization': 'test'})
            with self.assertRaises(ValueError):
                download_pexels(found[0], '/tmp', {'destinations': ['youtube'], 'search_network': 'on'}, transport)
        with patch.dict(os.environ, {'PEXELS_API_KEY': ''}):
            with self.assertRaises(ValueError):
                search_pexels('mountain', 'image', POLICY, transport)

    def test_host_mime_size_and_manual_only(self):
        candidate = {'provider': 'pexels', 'provider_id': 42, 'kind': 'image',
                     'page_url': 'https://www.pexels.com/photo/42/',
                     'media_url': 'https://images.pexels.com/photos/42/photo.jpg'}
        good = lambda url, headers: {'status': 200, 'headers': {'content-type': 'image/jpeg'}, 'body': b'\xff\xd8\xffimage'}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'PEXELS_API_KEY': 'test'}):
            self.assertTrue(download_pexels(candidate, temp, POLICY, good).is_file())
            with self.assertRaises(ValueError):
                download_pexels({**candidate, 'media_url': 'https://example.org/x.jpg'}, temp, POLICY, good)
            with self.assertRaises(ValueError):
                download_pexels(candidate, Path(temp) / 'small', POLICY, good, max_bytes=2)
        with self.assertRaises(ValueError):
            manual_import_only('pixabay')


if __name__ == '__main__':
    unittest.main()
