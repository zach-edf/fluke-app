from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from apps.cli._bootstrap import ensure_repo_paths

ensure_repo_paths()

from apps.cli.runtime import default_database_path


class CliMainTests(unittest.TestCase):
    def test_default_database_path_is_side_effect_free(self) -> None:
        with mock.patch("pathlib.Path.mkdir", side_effect=AssertionError("mkdir should not be called")):
            path = default_database_path()
        self.assertTrue(path.endswith("fluke.db"))

    def test_version_command_does_not_touch_database_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-m", "apps.cli.main", "--version"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("fluke ", result.stdout)


if __name__ == "__main__":
    unittest.main()
