#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
versions.env (version-pin single source of truth) のテスト。

バージョンピンは従来複数ファイルに重複定義されており、コメントで手動同期を
要求していた。versions.env に一元化し、消費者(Dockerfile、src/playwright_driver.py)
がそこから読むことを検証する(1ファクト1箇所)。
"""

import re
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = Path(__file__).parent.parent
VERSIONS_ENV = PROJECT_ROOT / "versions.env"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"


def parse_versions_env(path: Path) -> dict:
    """#・空行を無視して KEY=VALUE を読む(実装側と同じ規約)"""
    versions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            versions[key.strip()] = value.strip()
    return versions


class TestVersionsEnvFile(unittest.TestCase):
    """versions.env そのものの存在と形式"""

    def test_versions_env_exists(self):
        """versions.env がリポジトリ直下に存在する"""
        self.assertTrue(VERSIONS_ENV.is_file())

    def test_gms_ref_format(self):
        """GMS_REF は vX.Y.Z 形式"""
        versions = parse_versions_env(VERSIONS_ENV)
        self.assertIn("GMS_REF", versions)
        self.assertRegex(versions["GMS_REF"], r"^v\d+\.\d+\.\d+$")

    def test_go_version_format(self):
        """GO_VERSION は X.Y.Z 形式"""
        versions = parse_versions_env(VERSIONS_ENV)
        self.assertIn("GO_VERSION", versions)
        self.assertRegex(versions["GO_VERSION"], r"^\d+\.\d+\.\d+$")

    def test_pw_cli_version_format(self):
        """PW_CLI_VERSION は X.Y.Z 形式"""
        versions = parse_versions_env(VERSIONS_ENV)
        self.assertIn("PW_CLI_VERSION", versions)
        self.assertRegex(versions["PW_CLI_VERSION"], r"^\d+\.\d+\.\d+$")


class TestPlaywrightDriverReadsVersionsEnv(unittest.TestCase):
    """src/playwright_driver.py が versions.env から PW_CLI_VERSION を読んでいる"""

    def test_pw_cli_version_matches_file(self):
        from src import playwright_driver
        versions = parse_versions_env(VERSIONS_ENV)
        self.assertEqual(playwright_driver.PW_CLI_VERSION, versions["PW_CLI_VERSION"])

    def test_no_hardcoded_pw_cli_version(self):
        """PW_CLI_VERSION のハードコード代入が残っていない(メインロジックがファイルを読む)"""
        source = (PROJECT_ROOT / "src" / "playwright_driver.py").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r'^PW_CLI_VERSION\s*=\s*"', source, re.MULTILINE),
            "playwright_driver.py に PW_CLI_VERSION のハードコードが残っている",
        )


class TestDockerfileReadsVersionsEnv(unittest.TestCase):
    """Dockerfile が versions.env を参照し、GMS_REF をハードコードしていない"""

    def test_no_hardcoded_gms_ref_arg(self):
        """ARG GMS_REF=v... のハードコードが存在しない"""
        content = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"^ARG\s+GMS_REF\s*=\s*v\d", content, re.MULTILINE),
            "Dockerfile に GMS_REF のハードコードが残っている",
        )

    def test_references_versions_env(self):
        """versions.env への参照がある"""
        content = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("versions.env", content)


if __name__ == "__main__":
    unittest.main()
