import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness.cloud_transcript import ProviderFailure, _chunks, transcribe_cloud
from video_harness.common import fingerprint


class FakeTranscriptions:
    def __init__(self, semantic='こんにちは', timed='こんにちは'):
        self.calls = []
        self.semantic = semantic
        self.timed = timed

    def create(self, **kwargs):
        self.calls.append({k: v for k, v in kwargs.items() if k != 'file'})
        if kwargs['response_format'] == 'json':
            return {'text': self.semantic}
        return {'text': self.timed,
                'words': [{'start': 0.2, 'end': 0.6, 'word': 'こんにちは'}],
                'segments': [{'start': 0.2, 'end': 0.6, 'text': self.timed}]}


class FakeClient:
    def __init__(self, responses):
        self.audio = type('Audio', (), {'transcriptions': responses})()


class CloudTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'input.mov'
        self.source.write_bytes(b'private source')
        self.cache = self.root / 'cache'
        self.responses = FakeTranscriptions()

    def fake_run(self, cmd, log):
        Path(cmd[-1]).write_bytes(b'mp3 content')
        Path(log).write_text('extracted')

    def invoke(self, provider='openai', duration=2.0, transcription=None, probe_data=None, run_fn=None):
        info = {'format': {'duration': str(duration), 'start_time': '0'},
                'streams': [{'codec_type': 'video', 'start_time': '0', 'duration': str(duration)},
                            {'codec_type': 'audio', 'start_time': '0', 'duration': str(duration)}]}
        with patch('video_harness.cloud_transcript.probe', return_value=probe_data or info), \
             patch('video_harness.cloud_transcript.run', side_effect=run_fn or self.fake_run), \
             patch('video_harness.cloud_transcript._client', return_value=(FakeClient(self.responses), 'fake-sdk')):
            return transcribe_cloud({'source': str(self.source), 'transcription': transcription or {},
                                     'cloud_permission': {'source_sha256': fingerprint(self.source)['sha256'],
                                                          'policy': 'allow', 'providers': [provider],
                                                          'basis': 'synthetic test fixture'}}, provider, self.cache)

    def test_two_requests_and_immutable_cached_result(self):
        result = self.invoke()
        data = json.loads(result.read_text())
        self.assertEqual(data['backend']['name'], 'openai')
        self.assertEqual(data['backend']['settings']['text_model'], 'gpt-transcribe')
        self.assertEqual(data['words'][0]['probability'], 0.0)
        self.assertFalse(data['backend']['settings']['word_probability_available'])
        self.assertTrue(any('confidence unavailable' in warning for warning in data['warnings']))
        self.assertEqual(len(self.responses.calls), 2)
        self.assertEqual(self.responses.calls[0]['extra_body'], {'languages': ['ja']})
        self.assertEqual(self.responses.calls[1]['timestamp_granularities'], ['word', 'segment'])
        self.assertEqual(self.responses.calls[1]['model'], 'whisper-1')
        self.assertEqual(self.invoke(), result)
        self.assertEqual(len(self.responses.calls), 2)
        raw = result.parent / 'chunk-0000-responses.json'
        self.assertTrue(raw.is_file())
        self.assertTrue((result.parent / 'chunk-0000-manifest.json').is_file())
        self.assertIn('こんにちは', (result.parent / 'transcript.txt').read_text())
        result.unlink()
        (result.parent / 'transcript.txt').unlink()
        self.assertEqual(self.invoke(), result)
        self.assertEqual(len(self.responses.calls), 2)

    def test_multiple_chunks_offset_words_and_mismatch_warning(self):
        self.responses.semantic = '別の語'
        result = self.invoke(duration=301.0)
        data = json.loads(result.read_text())
        self.assertEqual(_chunks(300.0000001), [(0.0, 300.0)])
        self.assertEqual(_chunks(600.0), [(0.0, 300.0), (300.0, 300.0)])
        self.assertEqual(_chunks(901.0), [(0.0, 300.0), (300.0, 300.0), (600.0, 300.0), (900.0, 1.0)])
        self.assertEqual(_chunks(301.0), [(0.0, 300.0), (300.0, 1.0)])
        self.assertEqual([word['start'] for word in data['words']], [0.2, 300.2])
        self.assertEqual([word['end'] for word in data['words']], [0.6, 300.6])
        self.assertEqual(len(self.responses.calls), 4)
        self.assertEqual(len(data['warnings']), 3)
        self.assertIn('別の語', data['semantic_text'])

    def test_azure_models_and_request_languages(self):
        env = {'AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT': 'text-deployment',
               'AZURE_OPENAI_TIMESTAMP_DEPLOYMENT': 'time-deployment'}
        with patch.dict('os.environ', env):
            result = self.invoke(provider='azure')
        data = json.loads(result.read_text())
        self.assertEqual(data['backend']['settings']['text_model'], 'text-deployment')
        self.assertEqual(self.responses.calls[0]['model'], 'text-deployment')
        self.assertEqual(self.responses.calls[0]['language'], 'ja')
        self.assertEqual(self.responses.calls[1]['model'], 'time-deployment')

    def test_cache_tamper_and_no_credentials_in_artifacts(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'secret-canary'}):
            result = self.invoke()
            raw = result.parent / 'chunk-0000-responses.json'
            raw.write_text(raw.read_text().replace('こんにちは', '改変'))
            for item in result.parent.iterdir():
                if item.is_file():
                    self.assertNotIn('secret-canary', item.read_bytes().decode(errors='ignore'))
            (result.parent / 'transcript.json').unlink()
            (result.parent / 'transcript.txt').unlink()
            with self.assertRaisesRegex(ValueError, 'response changed'):
                self.invoke()

    def test_empty_semantic_text_fails(self):
        self.responses.semantic = ''
        with self.assertRaisesRegex(ProviderFailure, 'no semantic text'):
            self.invoke()

    def test_empty_timing_words_fails(self):
        original = self.responses.create

        def no_words(**kwargs):
            value = original(**kwargs)
            if kwargs['response_format'] == 'verbose_json':
                value['words'] = []
            return value

        self.responses.create = no_words
        with self.assertRaisesRegex(ProviderFailure, 'no words'):
            self.invoke()

    def test_language_and_request_limits_are_recorded_and_sent(self):
        settings = {'language': 'en', 'request_timeout_seconds': 35, 'max_retries': 0}
        result = self.invoke(transcription=settings)
        data = json.loads(result.read_text())
        self.assertEqual(data['language'], 'en')
        self.assertEqual(self.responses.calls[0]['extra_body'], {'languages': ['en']})
        self.assertEqual(self.responses.calls[1]['language'], 'en')
        self.assertEqual(data['backend']['settings']['request_timeout_seconds'], 35)
        self.assertEqual(data['backend']['settings']['max_retries'], 0)

    def test_timestamps_outside_chunk_or_nonfinite_fail(self):
        original = self.responses.create
        for bad in (-0.1, float('nan'), 2.1):
            with self.subTest(start=bad):
                self.responses.calls.clear()
                def broken(**kwargs):
                    value = original(**kwargs)
                    if kwargs['response_format'] == 'verbose_json':
                        value['words'][0]['start'] = bad
                    return value
                self.responses.create = broken
                with tempfile.TemporaryDirectory() as alternate:
                    with patch.object(self, 'cache', Path(alternate)):
                        with self.assertRaisesRegex(ProviderFailure, 'invalid timed words'):
                            self.invoke()
                self.responses.create = original

    def test_zero_length_timed_word_is_omitted_with_warning(self):
        original = self.responses.create
        def zero_word(**kwargs):
            value = original(**kwargs)
            if kwargs['response_format'] == 'verbose_json':
                value['words'].insert(0, {'start': 0.1, 'end': 0.1, 'word': 'artifact'})
            return value
        self.responses.create = zero_word
        data = json.loads(self.invoke().read_text())
        self.assertEqual(len(data['words']), 1)
        self.assertTrue(any('skipped empty' in warning for warning in data['warnings']))

    def test_partial_tracks_rejected_before_api(self):
        base = {'format': {'duration': '2', 'start_time': '0'},
                'streams': [{'codec_type': 'video', 'start_time': '0', 'duration': '2'}]}
        for audio in (None, {'codec_type': 'audio', 'start_time': '0.2', 'duration': '1.8'},
                      {'codec_type': 'audio', 'start_time': '0', 'duration': '1.6'}):
            with self.subTest(audio=audio):
                probe_data = {**base, 'streams': base['streams'] + ([audio] if audio else [])}
                with self.assertRaisesRegex(ValueError, 'full-length zero-start'):
                    self.invoke(probe_data=probe_data)
        self.assertEqual(self.responses.calls, [])

    def test_source_change_during_extraction_blocks_upload(self):
        def change_source(cmd, log):
            self.fake_run(cmd, log)
            self.source.write_bytes(b'changed before upload')
        with self.assertRaisesRegex(ValueError, 'before cloud upload'):
            self.invoke(run_fn=change_source)
        self.assertEqual(self.responses.calls, [])

    def test_completed_cache_still_checks_raw_response_hash(self):
        result = self.invoke()
        raw = result.parent / 'chunk-0000-responses.json'
        raw.write_text(raw.read_text().replace('こんにちは', 'changed'))
        with self.assertRaisesRegex(ValueError, 'response changed'):
            self.invoke()


if __name__ == '__main__':
    unittest.main()
