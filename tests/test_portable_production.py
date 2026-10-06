import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from tests import test_production as fixture_helpers
from video_harness.common import read, fingerprint, probe
from video_harness.delivery import bundle
from video_harness.delivery_production import verify_dependencies
from video_harness.edl import build_plan
from video_harness.editing import render_edit


class PortableProductionTests(unittest.TestCase):
    def render_fixture(self, root):
        cfg = fixture_helpers.ProductionTests().fixture(root, mixed=True)
        source = root / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n',
            '-f', 'lavfi', '-i', 'color=c=gray:s=128x128:r=30:d=2',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
        cfg.update(source=str(source), name='Portable Mix Fixture', input_color='rec709',
            evidence_kind='synthetic', render_cache_root=str(root / 'cache'),
            audio={'normalize': True, 'target_lufs': -16, 'true_peak_db': -1.5, 'loudness_range': 7})
        transcript = {'version': 1, 'source': fingerprint(source), 'duration': 2,
                      'words': [{'id': 'fixture-word', 'start': .2, 'end': 1.8, 'text': 'Fixture', 'probability': 1}],
                      'segments': []}
        plan = build_plan(cfg, transcript, [])
        out = root / 'render'
        render_edit(cfg, plan, out, preview=False)
        pairs = [('video', 'video.mp4'), ('audio', 'audio-only.mp3'),
                 ('xml', 'production-timeline.fcpxml'), ('subtitles', 'subtitles.srt'),
                 ('lut', 'look.cube'), ('mapping', 'frame-mapping.json'), ('plan', 'plan.json'),
                 ('production', 'production.json'), ('fcp_production', 'fcp-production.json'),
                 ('final_mix', 'final-mix.wav'), ('finished_picture', 'finished-picture.mp4')]
        files = {label: fingerprint(out / name) for label, name in pairs}
        return {'id': 'fixture', 'path': str(out), 'preview': False, 'files': files,
                'plan': files['plan'], 'project': {}}, cfg

    def test_mix_bundle_relinks_and_survives_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render, _ = self.render_fixture(root)
            picture = Path(render['files']['finished_picture']['path'])
            self.assertTrue(any(s['codec_type'] == 'video' for s in probe(picture)['streams']))
            self.assertFalse(any(s['codec_type'] == 'audio' for s in probe(picture)['streams']))
            self.assertTrue(Path(render['files']['final_mix']['path']).is_file())
            self.assertEqual(read(render['files']['fcp_production']['path'])['picture_file'],
                             render['files']['finished_picture'])
            delivery = root / 'delivery'
            manifest = read(bundle(render, {}, 'fcp', delivery, accepted=True))
            self.assertEqual(manifest['status'], 'needs_manual_checks')
            self.assertEqual(manifest['fidelity']['mode'], 'mix')
            refs = ET.parse(delivery / 'timeline.fcpxml').findall('./resources/asset/media-rep')
            self.assertTrue(all(n.get('src').startswith('./media/') for n in refs))
            self.assertEqual({d['kind'] for d in verify_dependencies(delivery)['dependencies']}, {'finished_video', 'final_pcm'})
            moved = root / 'moved'
            shutil.move(delivery, moved)
            shutil.rmtree(root / 'render')
            self.assertEqual(verify_dependencies(moved)['mode'], 'mix')
            self.assertIn('Do not apply look.cube again', (moved / 'FCP-INSTRUCTIONS.txt').read_text())
            media = next((moved / 'media').iterdir())
            media.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'changed'):
                verify_dependencies(moved)

    def test_missing_or_audio_bearing_picture_rejected_before_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render, _ = self.render_fixture(root)
            original_picture = render['files'].pop('finished_picture')
            with self.assertRaisesRegex(ValueError, 'Silent finished-picture evidence'):
                bundle(render, {}, 'fcp', root / 'missing')
            self.assertFalse((root / 'missing').exists())
            render['files']['finished_picture'] = render['files']['video']
            evidence_path = Path(render['files']['fcp_production']['path'])
            evidence = read(evidence_path)
            evidence['picture_file'] = render['files']['video']
            from video_harness.common import write
            evidence_path.unlink()
            write(evidence_path, evidence)
            render['files']['fcp_production'] = fingerprint(evidence_path)
            with self.assertRaisesRegex(ValueError, 'Finished picture must have video and no audio'):
                bundle(render, {}, 'fcp', root / 'audio-bearing')
            self.assertFalse((root / 'audio-bearing').exists())
