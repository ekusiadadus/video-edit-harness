"""Exercise CLI dispatch all the way to LUT generation without encoding media."""
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_harness import cli


class CLIRenderExecution(unittest.TestCase):
    def test_grading_commands_reach_lut_and_renderer(self):
        for command in ('preview', 'render', 'compare'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cfg = {'name': 'demo', 'source': str(root/'source.mp4'),
                       'input_color': 'rec709', 'use_case': 'indoor_talk',
                       'style': 'natural', 'preview': {'start': 0, 'duration': 1}}
                argv = ['video-harness', command, str(root/'project.json'),
                        '--output', str(root/'result')]
                if command in ('preview', 'compare'):
                    argv += ['--styles', 'natural']
                if command == 'compare':
                    argv += ['--use-cases', 'indoor_talk']
                with patch('sys.argv', argv), \
                     patch.object(cli, 'project', return_value=cfg), \
                     patch.object(cli, 'probe', return_value={'format': {'duration': '2'}}), \
                     patch.object(cli, 'evidence_run', return_value=contextlib.nullcontext()), \
                     patch.object(cli, 'build_lut', return_value=root/'look.cube') as lut, \
                     patch.object(cli, 'render', return_value=root/'video.mp4') as render, \
                     patch.object(cli, 'evaluate'), patch.object(cli, 'gallery'):
                    cli.main()
                lut.assert_called_once()
                render.assert_called_once()
                self.assertEqual(render.call_args.args[-1], command != 'render')
