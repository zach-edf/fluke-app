from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from fluke_core import paths
from fluke_app.workflow_catalog import default_workflow_directory
from fluke_plugins.loader import default_plugin_root


class FrozenPathTests(unittest.TestCase):
    def test_not_frozen_by_default(self) -> None:
        self.assertFalse(paths.is_frozen())
        self.assertIsNone(paths.bundle_root())
        self.assertIsNone(paths.bundled_data_dir("workflows"))

    def test_bundle_root_uses_meipass_when_frozen(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(Path("/tmp/bundle")), create=True
        ):
            self.assertTrue(paths.is_frozen())
            self.assertEqual(paths.bundle_root(), Path("/tmp/bundle"))

    def test_bundled_data_dir_returns_none_when_missing(self, ) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(Path("/nonexistent-bundle-root")), create=True
        ):
            self.assertIsNone(paths.bundled_data_dir("workflows"))

    def test_bundled_data_dir_returns_existing_dir(self) -> None:
        # Point the bundle root at the repo so ``workflows`` resolves.
        repo_root = Path(__file__).resolve().parents[2]
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(repo_root), create=True
        ):
            resolved = paths.bundled_data_dir("workflows")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved, repo_root / "workflows")

    def test_default_workflow_directory_prefers_bundle(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(repo_root), create=True
        ):
            self.assertEqual(default_workflow_directory(), repo_root / "workflows")

    def test_default_plugin_root_prefers_bundle(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(repo_root), create=True
        ):
            self.assertEqual(default_plugin_root(), repo_root / "plugins")

    def test_default_paths_use_source_layout_when_not_frozen(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.assertEqual(default_workflow_directory(), repo_root / "workflows")
        self.assertEqual(default_plugin_root(), repo_root / "plugins")


if __name__ == "__main__":
    unittest.main()


class DefaultExportDirectoryTests(unittest.TestCase):
    def test_source_checkout_keeps_relative_exports(self) -> None:
        self.assertEqual(paths.default_export_directory(), Path("exports"))

    def test_frozen_prefers_documents(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            Path, "exists", return_value=True
        ):
            resolved = paths.default_export_directory()
        self.assertEqual(resolved, Path.home() / "Documents" / "Fluke Community")

    def test_frozen_falls_back_to_user_data_dir_without_documents(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            Path, "exists", return_value=False
        ):
            resolved = paths.default_export_directory()
        self.assertEqual(resolved, paths.user_data_dir() / "exports")
