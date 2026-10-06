import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from video_harness.common import fingerprint
from video_harness.render_cache import RenderCache


class RenderCacheTests(unittest.TestCase):
    def test_reuse_invalidation_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mov'
            source.write_bytes(b'source')
            cache = RenderCache(root / 'cache', source, fingerprint(source))
            calls = []
            def build(artifact, log):
                calls.append(1)
                artifact.write_bytes(b'encoded')
                log.write_text('command and stderr')
            first = cache.get('video', {'interval': '0/1-1/1', 'grade': 'a'}, '.mov', root / 'a.mov', build)
            second = cache.get('video', {'interval': '0/1-1/1', 'grade': 'a'}, '.mov', root / 'b.mov', build)
            third = cache.get('video', {'interval': '0/1-1/1', 'grade': 'b'}, '.mov', root / 'c.mov', build)
            self.assertEqual((first['reused'], second['reused'], third['reused']), (False, True, False))
            self.assertEqual(len(calls), 2)
            (root / 'cache' / 'video' / first['key'] / 'artifact.mov').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'Corrupted cache'):
                cache.get('video', {'interval': '0/1-1/1', 'grade': 'a'}, '.mov', root / 'd.mov', build)
            self.assertEqual((root / 'a.mov').read_bytes(), b'encoded')
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                cache.get('video', {'interval': '0/1-1/1', 'grade': 'b'}, '.mov', root / 'e.mov', build)

    def test_one_builder_for_concurrent_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mov'
            source.write_bytes(b'source')
            calls = []
            def task(i):
                cache = RenderCache(root / 'cache', source, fingerprint(source))
                def build(artifact, log):
                    calls.append(1)
                    artifact.write_bytes(b'encoded')
                    log.write_text('log')
                return cache.get('pcm', {'range': [0, 1]}, '.wav', root / f'{i}.wav', build)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                events = list(pool.map(task, range(4)))
            self.assertEqual(len(calls), 1)
            self.assertEqual(sum(not e['reused'] for e in events), 1)



    def test_sealed_auxiliary_copy_hit_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mov'; source.write_bytes(b'source')
            cache = RenderCache(root / 'cache', source, fingerprint(source))
            def build(artifact, log):
                artifact.write_bytes(b'mix'); log.write_text('log')
                (artifact.parent / 'speech.wav').write_bytes(b'speech')
                folder = artifact.parent / 'gains'; folder.mkdir()
                (folder / 'manifest.json').write_bytes(b'gain proof')
            event = cache.get('mix', {'gain_schema': 1}, '.wav', root / 'first.wav', build,
                              auxiliary_paths=['speech.wav', 'gains'])
            hit = cache.get('mix', {'gain_schema': 1}, '.wav', root / 'second.wav', build,
                            auxiliary_paths=['speech.wav', 'gains'])
            self.assertTrue(hit['reused'])
            destinations = {'speech.wav': root / 'retained.wav', 'gains': root / 'retained-gains'}
            copied = cache.copy_auxiliary(hit, destinations)
            self.assertEqual(set(copied), {'speech.wav', 'gains/manifest.json'})
            self.assertEqual((root / 'retained.wav').read_bytes(), b'speech')
            self.assertEqual((root / 'retained-gains/manifest.json').read_bytes(), b'gain proof')
            with self.assertRaises(FileExistsError):
                cache.copy_auxiliary(hit, destinations)
            (cache.root / 'mix' / event['key'] / 'gains/manifest.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Corrupted cache'):
                cache.get('mix', {'gain_schema': 1}, '.wav', root / 'third.wav', build,
                          auxiliary_paths=['speech.wav', 'gains'])
            with self.assertRaisesRegex(ValueError, 'auxiliary content changed'):
                cache.copy_auxiliary(hit, {'speech.wav': root / 'other.wav', 'gains': root / 'other-gains'})
            self.assertFalse((root / 'other.wav').exists())

    def test_auxiliary_metadata_and_unexpected_member_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mov'; source.write_bytes(b'source')
            cache = RenderCache(root / 'cache', source, fingerprint(source))
            def build(artifact, log):
                artifact.write_bytes(b'mix'); log.write_text('log')
                folder = artifact.parent / 'gains'; folder.mkdir()
                (folder / 'manifest.json').write_bytes(b'proof')
            event = cache.get('mix', {}, '.wav', root / 'mix.wav', build, auxiliary_paths=['gains'])
            folder = cache.root / 'mix' / event['key']
            (folder / 'gains/added.npy').write_bytes(b'new unknown member')
            with self.assertRaisesRegex(ValueError, 'auxiliary content changed'):
                cache.copy_auxiliary(event, {'gains': root / 'copy'})
            (folder / 'gains/added.npy').unlink()
            (folder / 'meta.json').write_text((folder / 'meta.json').read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'auxiliary metadata changed'):
                cache.copy_auxiliary(event, {'gains': root / 'copy'})

if __name__ == '__main__':
    unittest.main()
