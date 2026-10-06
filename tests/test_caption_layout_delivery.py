"""Portable caption proof is bound to reviewed synthetic portrait video."""
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_session import SessionFixture
from tests.test_feedback import review_report
from video_harness.common import fingerprint, read, write
from video_harness.delivery import verify_completion


class CaptionLayoutDeliveryTests(unittest.TestCase):
    def test_portable_layout_retains_visible_lines_without_unused_terms_or_paths(self):
        fixture = SessionFixture()
        self.addCleanup(fixture.close)
        fixture.selected()
        render = fixture.render(preview=False)
        fixture.session.review(render['id'], review_report(render), 'automation')
        video = fixture.root / 'portrait.mp4'
        video.write_bytes(b'synthetic portrait fixture')
        result = fixture.root / 'portrait-result.json'
        write(result, {'technical_status': 'pass', 'source': render['files']['video'],
            'video': fingerprint(video), 'framing': 'fit', 'subtitles_source': None,
            'font_source': None, 'caption_layout': {'version': 1, 'language': 'en',
                'protected_phrases': ['unused-private-term'], 'max_width': 820, 'max_lines': 3,
                'runtime': {'regex': '0.0.0', 'budoux': None, 'private_path': '/Users/private/runtime'}},
            'caption_lines': [{'start': 0., 'end': .35, 'text': 'One line', 'lines': ['One line'], 'source_path': '/Users/private/caption-source'}]})
        derivative = fixture.session.register_derivative(render['id'], result, 'automation')
        fixture.session.review_derivative(derivative['id'], {'video_sha256': derivative['video']['sha256'],
            'checks': [{'id': key, 'status': 'pass', 'basis': 'synthetic', 'note': 'Synthetic fixture'}
                       for key in ('framing', 'captions', 'audio', 'playback')]}, 'automation')
        delivery = fixture.session.package(render['id'], 'mp4', 'automation', derivative_id=derivative['id'])
        folder = Path(delivery['artifact']['path']).parent
        public = read(folder / 'portrait-caption-layout.json')
        self.assertEqual(public['original_result_sha256'], fingerprint(result)['sha256'])
        self.assertEqual(public['caption_lines'][0]['lines'], ['One line'])
        self.assertEqual(public['caption_layout']['protected_phrase_count'], 1)
        self.assertNotIn('unused-private-term', (folder / 'portrait-caption-layout.json').read_text())
        self.assertNotIn('/Users/private', (folder / 'portrait-caption-layout.json').read_text())
        self.assertNotIn('settings_sha256', public['caption_layout'])
        self.assertNotIn(str(fixture.root), (folder / 'portrait-caption-layout.json').read_text())
        fixture.session.finish(delivery['id'], 'automation')
        with tempfile.TemporaryDirectory() as temporary:
            moved = Path(temporary) / 'delivery'
            shutil.copytree(folder, moved)
            self.assertEqual(verify_completion(moved)['status'], 'synthetic_complete')
            (moved / 'portrait-caption-layout.json').write_text('{}')
            with self.assertRaises(ValueError):
                verify_completion(moved)
