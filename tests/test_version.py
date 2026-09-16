"""Version and location come from the package actually running."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import omagenda
from tests.test_watch_sync import cli


class VersionTest(unittest.TestCase):
    def test_version_text_and_json_resolve_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'installed'
            folder.mkdir()
            (folder / 'manifest.json').write_text('{"version": "9.8.7"}')
            link = Path(tmp) / 'developer-link'
            link.symlink_to(folder, target_is_directory=True)
            with patch.object(omagenda, '__file__', str(link / 'omagenda/__init__.py')):
                for args in (['--version'], ['--version', '--json'], ['--json', '--version']):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(cli.main(args), 0)
                    if '--json' in args:
                        self.assertEqual(json.loads(out.getvalue()), {'version': '9.8.7', 'path': str(folder)})
                    else:
                        self.assertEqual(out.getvalue(), f'omagenda 9.8.7 ({folder})\n')

    def test_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp,              patch.object(omagenda, '__file__', str(Path(tmp) / 'omagenda/__init__.py')),              contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--version']), 1)

    def test_no_command_still_requires_action(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            cli.main([])
        self.assertEqual(caught.exception.code, 2)
