#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for src/playwright_driver.py (the local Playwright driver assembly logic)

Background: the playwright-go the scraper depends on tries to fetch the driver
from a decommissioned CDN (playwright.azureedge.net) and fails with 404. The
workaround that used to live in the Dockerfile (laying out a node executable
plus the npm playwright-core package at PLAYWRIGHT_DRIVER_PATH) was extracted
into a shared module so the Docker build and local runs go through the same
logic. See src/playwright_driver.py's module docstring for details.
"""
import io
import contextlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import playwright_driver


FAKE_NODE_SCRIPT = """#!/bin/sh
echo "Version {version}"
"""


def _make_fake_driver(driver_dir: Path, version: str):
    """Create the minimal driver dir (node executable + package/cli.js) that passes validation"""
    driver_dir.mkdir(parents=True, exist_ok=True)
    node_path = driver_dir / "node"
    node_path.write_text(FAKE_NODE_SCRIPT.format(version=version))
    node_path.chmod(node_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    package_dir = driver_dir / "package"
    package_dir.mkdir(exist_ok=True)
    (package_dir / "cli.js").write_text("// fake playwright-core cli\n")


def _make_node_archive(archive_path: Path, version: str, node_version: str):
    """Create a tar.xz with the same layout as nodejs.org distributions (node-vX-<platform>/bin/node)"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / f"node-v{node_version}-{playwright_driver._node_platform_tag()}"
        bin_dir = root / "bin"
        bin_dir.mkdir(parents=True)
        node_path = bin_dir / "node"
        node_path.write_text(FAKE_NODE_SCRIPT.format(version=version))
        node_path.chmod(node_path.stat().st_mode | stat.S_IXUSR)
        with tarfile.open(archive_path, "w:xz") as tar:
            tar.add(root, arcname=root.name)


def _make_package_archive(archive_path: Path):
    """Create a tar.gz with the same layout as npm registry tgz files (package/cli.js)"""
    with tempfile.TemporaryDirectory() as tmp:
        package_dir = Path(tmp) / "package"
        package_dir.mkdir()
        (package_dir / "cli.js").write_text("// fake playwright-core cli\n")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(package_dir, arcname="package")


class TestDriverIsValid(unittest.TestCase):
    """driver_is_valid(): validation of an existing driver directory"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.driver_dir = Path(self.tmp.name) / "driver"

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_driver_returns_true(self):
        _make_fake_driver(self.driver_dir, "1.57.0")
        self.assertTrue(playwright_driver.driver_is_valid(self.driver_dir, "1.57.0"))

    def test_missing_cli_js_returns_false(self):
        _make_fake_driver(self.driver_dir, "1.57.0")
        (self.driver_dir / "package" / "cli.js").unlink()
        self.assertFalse(playwright_driver.driver_is_valid(self.driver_dir, "1.57.0"))

    def test_missing_node_returns_false(self):
        _make_fake_driver(self.driver_dir, "1.57.0")
        (self.driver_dir / "node").unlink()
        self.assertFalse(playwright_driver.driver_is_valid(self.driver_dir, "1.57.0"))

    def test_version_mismatch_returns_false(self):
        _make_fake_driver(self.driver_dir, "1.52.0")
        self.assertFalse(playwright_driver.driver_is_valid(self.driver_dir, "1.57.0"))

    def test_nonexistent_dir_returns_false(self):
        self.assertFalse(
            playwright_driver.driver_is_valid(self.driver_dir / "missing", "1.57.0")
        )


class TestEnsureDriver(unittest.TestCase):
    """ensure_driver(): returns valid drivers as-is, assembles invalid ones"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.driver_dir = Path(self.tmp.name) / "driver"

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_driver_skips_assembly(self):
        _make_fake_driver(self.driver_dir, "1.57.0")
        with patch.object(playwright_driver, "_download") as mock_download:
            result = playwright_driver.ensure_driver(self.driver_dir, "1.57.0")
        mock_download.assert_not_called()
        self.assertEqual(result, self.driver_dir)

    def test_assembles_driver_from_downloads(self):
        """Without node installed: fetch both the node and package archives and assemble"""

        def fake_download(url, dest):
            if "nodejs.org" in url:
                _make_node_archive(Path(dest), "1.57.0", playwright_driver.NODE_VERSION)
            elif "registry.npmjs.org" in url:
                _make_package_archive(Path(dest))
            else:
                raise AssertionError(f"予期しないURL: {url}")

        with patch.object(playwright_driver, "_download", side_effect=fake_download), \
             patch.object(playwright_driver.shutil, "which", return_value=None), \
             contextlib.redirect_stderr(io.StringIO()):
            result = playwright_driver.ensure_driver(self.driver_dir, "1.57.0")

        self.assertEqual(result, self.driver_dir)
        self.assertTrue(playwright_driver.driver_is_valid(self.driver_dir, "1.57.0"))

    def test_uses_system_node_when_available(self):
        """With a system node available, copy it and do not download node"""
        system_node = Path(self.tmp.name) / "system_node"
        system_node.write_text(FAKE_NODE_SCRIPT.format(version="1.57.0"))
        system_node.chmod(system_node.stat().st_mode | stat.S_IXUSR)

        downloaded_urls = []

        def fake_download(url, dest):
            downloaded_urls.append(url)
            if "registry.npmjs.org" in url:
                _make_package_archive(Path(dest))
            else:
                raise AssertionError(f"nodeがあるのにダウンロードした: {url}")

        with patch.object(playwright_driver, "_download", side_effect=fake_download), \
             patch.object(playwright_driver.shutil, "which", return_value=str(system_node)), \
             contextlib.redirect_stderr(io.StringIO()):
            result = playwright_driver.ensure_driver(self.driver_dir, "1.57.0")

        self.assertTrue(all("registry.npmjs.org" in u for u in downloaded_urls))
        self.assertTrue(playwright_driver.driver_is_valid(result, "1.57.0"))

    def test_raises_when_assembly_produces_invalid_driver(self):
        """RuntimeError when validation still fails after assembly (no silent breakage)"""

        def fake_download(url, dest):
            if "nodejs.org" in url:
                # A node claiming an unexpected version → validation should fail
                _make_node_archive(Path(dest), "9.99.9", playwright_driver.NODE_VERSION)
            elif "registry.npmjs.org" in url:
                _make_package_archive(Path(dest))

        with patch.object(playwright_driver, "_download", side_effect=fake_download), \
             patch.object(playwright_driver.shutil, "which", return_value=None), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError):
                playwright_driver.ensure_driver(self.driver_dir, "1.57.0")

    def test_rebuilds_when_existing_driver_has_wrong_version(self):
        """An existing driver with the wrong version gets reassembled"""
        _make_fake_driver(self.driver_dir, "1.52.0")

        def fake_download(url, dest):
            if "nodejs.org" in url:
                _make_node_archive(Path(dest), "1.57.0", playwright_driver.NODE_VERSION)
            elif "registry.npmjs.org" in url:
                _make_package_archive(Path(dest))

        with patch.object(playwright_driver, "_download", side_effect=fake_download), \
             patch.object(playwright_driver.shutil, "which", return_value=None), \
             contextlib.redirect_stderr(io.StringIO()):
            result = playwright_driver.ensure_driver(self.driver_dir, "1.57.0")

        self.assertTrue(playwright_driver.driver_is_valid(result, "1.57.0"))


class TestEnsureDriverDefaults(unittest.TestCase):
    """ensure_driver()'s resolution when driver_dir is omitted"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_var_takes_precedence_when_arg_omitted(self):
        """When PLAYWRIGHT_DRIVER_PATH is set, look there (the Docker runtime path;
        if this breaks, Docker ignores the baked-in driver and reassembles every time)"""
        env_driver = Path(self.tmp.name) / "env_driver"
        _make_fake_driver(env_driver, "1.57.0")
        with patch.dict(os.environ, {"PLAYWRIGHT_DRIVER_PATH": str(env_driver)}):
            result = playwright_driver.ensure_driver(None, "1.57.0")
        self.assertEqual(result, env_driver)


class TestDriverIsValidErrorPaths(unittest.TestCase):
    """driver_is_valid() error paths"""

    def test_broken_node_returns_false_instead_of_raising(self):
        """When node cannot run (e.g. leftovers of an interrupted assembly), return
        False without leaking the exception. A leaked exception blocks ensure_driver's
        reassembly and takes down the whole pipeline."""
        with tempfile.TemporaryDirectory() as tmp:
            driver_dir = Path(tmp) / "driver"
            _make_fake_driver(driver_dir, "1.57.0")
            node = driver_dir / "node"
            node.write_text("not a script, no shebang, not executable")
            node.chmod(0o644)
            self.assertFalse(playwright_driver.driver_is_valid(driver_dir, "1.57.0"))


class TestPipelineIntegration(unittest.TestCase):
    """GoogleMapsPipeline passes PLAYWRIGHT_DRIVER_PATH when running the scraper"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scraper_path = Path(self.tmp.name) / "fake_scraper"
        self.scraper_path.write_text("#!/bin/sh\nexit 0\n")
        self.scraper_path.chmod(self.scraper_path.stat().st_mode | stat.S_IXUSR)
        self.driver_dir = Path(self.tmp.name) / "driver"
        _make_fake_driver(self.driver_dir, "1.57.0")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_places_passes_driver_path_env_to_scraper(self):
        from src.pipeline import GoogleMapsPipeline

        pipeline = GoogleMapsPipeline(scraper_path=str(self.scraper_path))

        captured = {}
        real_popen = subprocess.Popen

        def spy_popen(cmd, **kwargs):
            captured["env"] = kwargs.get("env")
            return real_popen(["true"], stdout=kwargs.get("stdout"),
                              stderr=kwargs.get("stderr"), text=kwargs.get("text"))

        with patch.object(playwright_driver, "ensure_driver",
                          return_value=self.driver_dir) as mock_ensure, \
             patch("src.pipeline.subprocess.Popen", side_effect=spy_popen), \
             contextlib.redirect_stderr(io.StringIO()):
            pipeline.extract_places("テストクエリ")

        mock_ensure.assert_called_once()
        self.assertIsNotNone(captured["env"], "subprocessにenvが渡されていない")
        self.assertEqual(captured["env"].get("PLAYWRIGHT_DRIVER_PATH"), str(self.driver_dir))


if __name__ == "__main__":
    unittest.main(verbosity=2)
