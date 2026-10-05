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


if __name__ == '__main__':
    unittest.main()
