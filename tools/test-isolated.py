#!/usr/bin/env python3
"""Run Python tests with disposable defaults, including child CLI processes."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
with tempfile.TemporaryDirectory(prefix="omagenda-tests-") as tmp:
    base = Path(tmp)
    os.environ.update(OMAGENDA_CONFIG=str(base / "config.toml"),
                      OMAGENDA_STATE=str(base / "state"), OMAGENDA_VDIR=str(base / "calendars"))
    guard_bin = base / "bin"
    guard_bin.mkdir()
    secret_tool = guard_bin / "secret-tool"
    secret_tool.write_text("#!/bin/sh\nexit 1\n")
    secret_tool.chmod(0o700)
    os.environ["PATH"] = str(guard_bin) + os.pathsep + os.environ["PATH"]
    from omagenda import accounts, doctor
    with patch.object(accounts, "SECRETS_DIR", base / "secrets"), \
         patch.object(accounts, "PIMSYNC_CONFIG_DIR", base / "pimsync"), \
         patch.object(accounts, "PIMSYNC_STATUS_DIR", base / "pimsync-state"), \
         patch.object(doctor, "SHELL_JSON_PATH", base / "shell.json"):
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        sys.exit(not result.wasSuccessful())
