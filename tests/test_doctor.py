import unittest
from unittest.mock import patch

from video_harness.doctor import report


class DoctorTests(unittest.TestCase):
    def test_report_names_commands_and_never_exposes_credentials(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'private-value',
                                    'AZURE_OPENAI_API_KEY': 'another-private-value'}, clear=True):
            result = report()
        self.assertEqual(result['credentials_configured']['openai'], True)
        self.assertEqual(result['credentials_configured']['azure'], False)
        self.assertTrue(all(result['required_commands'].values()))
        self.assertTrue(all(result['session_actions'].values()))
        self.assertTrue(all(result['skill_paths_present'].values()))
        self.assertEqual(result['retime_features']['session_connected'], 'visual_and_speech')
        self.assertTrue(result['retime_features']['session_audio_video'])
        self.assertFalse(result['retime_features']['editable_fcp_retime'])
        self.assertNotIn('private-value', str(result))
        self.assertNotIn('another-private-value', str(result))


if __name__ == '__main__':
    unittest.main()
