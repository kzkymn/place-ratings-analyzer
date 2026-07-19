#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assemble a Playwright driver locally.

This module builds the driver that playwright-go expects — a node executable plus
the playwright-core npm package — from live sources (the system node or nodejs.org,
and the npm registry), and places it where PLAYWRIGHT_DRIVER_PATH points. When the
driver is already present there, playwright-go skips its own download entirely.

Why this exists: the playwright-go version the scraper depends on (v0.5700.1) tries
to fetch the driver from a decommissioned CDN (playwright.azureedge.net) and fails
with 404. The upstream fix only landed after playwright-go's module path was renamed,
so it cannot be pulled in; instead we assemble the same driver that fix would produce.

Both the Docker build (Dockerfile) and local runs (via src/pipeline.py) go through
this module, so the workaround logic lives in exactly one place. Once upstream moves
to the fixed playwright-go, this module and its call sites can be deleted wholesale.

Standalone usage (used by the Docker build):
    python src/playwright_driver.py --dest /opt/ms-playwright-go
"""

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

_project_root = Path(__file__).parent.parent


def load_versions(path: Path = None) -> dict:
    """versions.env（バージョンピンの single source of truth）を読む。

    形式: KEY=VALUE。# 始まりと空行は無視。
    ローダーをこのモジュールに置くのは、Docker ビルドで単体 COPY されて動く必要が
    あるため（自己完結・stdlib のみ）。
    """
    if path is None:
        path = _project_root / "versions.env"
    versions = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            versions[key.strip()] = value.strip()
    return versions


# playwright-go の playwrightCliVersion と一致している必要がある（結合の説明は versions.env 参照）
PW_CLI_VERSION = load_versions()["PW_CLI_VERSION"]

# Node.js version (LTS) downloaded when the system has no node
NODE_VERSION = "22.14.0"

DEFAULT_DRIVER_DIR = _project_root / ".playwright-driver" / PW_CLI_VERSION


def _diag(message: str) -> None:
    # stdout is the MCP stdio transport's channel, so diagnostics go to stderr
    # (same reason as pipeline._diag)
    print(message, file=sys.stderr)


def _node_platform_tag() -> str:
    """Platform identifier used by nodejs.org distributions (e.g. linux-x64)"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system in ("linux", "darwin") and arch:
        return f"{system}-{arch}"
    raise RuntimeError(
        f"サポートされていないプラットフォーム: {system}/{machine}。"
        "Dockerイメージの利用を検討してください。"
    )


def _download(url: str, dest: str) -> None:
    urllib.request.urlretrieve(url, dest)


def driver_is_valid(driver_dir: Path, version: str = PW_CLI_VERSION) -> bool:
    """Whether the driver dir holds a node executable plus package/cli.js of the expected version"""
    node_path = Path(driver_dir) / "node"
    cli_js = Path(driver_dir) / "package" / "cli.js"
    if not (node_path.exists() and cli_js.exists()):
        return False
    try:
        result = subprocess.run(
            [str(node_path), str(cli_js), "--version"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and version in result.stdout


def _install_node(driver_dir: Path) -> None:
    """Place a node executable directly under driver_dir (copy the system node if present, download otherwise)"""
    dest = driver_dir / "node"
    system_node = shutil.which("node")
    if system_node:
        _diag(f"  ✅ システムのnodeをコピー: {system_node}")
        shutil.copy2(system_node, dest)
        return

    tag = _node_platform_tag()
    archive_name = f"node-v{NODE_VERSION}-{tag}.tar.xz"
    url = f"https://nodejs.org/dist/v{NODE_VERSION}/{archive_name}"
    _diag(f"  📥 Node.js {NODE_VERSION} をダウンロード: {url}")
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        _download(url, str(archive_path))
        node_member = f"node-v{NODE_VERSION}-{tag}/bin/node"
        with tarfile.open(archive_path, "r:xz") as tar:
            member = tar.getmember(node_member)
            member.name = "node"
            tar.extract(member, driver_dir, filter="data")
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_package(driver_dir: Path, version: str) -> None:
    """Fetch playwright-core from the npm registry and extract it as package/"""
    url = f"https://registry.npmjs.org/playwright-core/-/playwright-core-{version}.tgz"
    _diag(f"  📥 playwright-core {version} をダウンロード: {url}")
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / "playwright-core.tgz"
        _download(url, str(archive_path))
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(driver_dir, filter="data")  # the tgz's top-level dir is package/


def ensure_driver(driver_dir: Path = None, version: str = PW_CLI_VERSION) -> Path:
    """Return the driver directory, assembling the driver first if it is not valid.

    Precedence: argument > PLAYWRIGHT_DRIVER_PATH env var > DEFAULT_DRIVER_DIR.
    In environments assembled at build time (like Docker) this just validates and
    returns immediately (no runtime network access or writes needed).
    """
    if driver_dir is None:
        env_path = os.environ.get("PLAYWRIGHT_DRIVER_PATH")
        driver_dir = Path(env_path) if env_path else DEFAULT_DRIVER_DIR
    driver_dir = Path(driver_dir)

    if driver_is_valid(driver_dir, version):
        return driver_dir

    _diag(f"🔧 Playwright driver {version} を組み立て中: {driver_dir}")
    if driver_dir.exists():
        shutil.rmtree(driver_dir)
    driver_dir.mkdir(parents=True)

    _install_node(driver_dir)
    _install_package(driver_dir, version)

    if not driver_is_valid(driver_dir, version):
        raise RuntimeError(
            f"Playwright driverの組み立てに失敗しました: {driver_dir} "
            f"(期待バージョン: {version})"
        )
    _diag(f"✅ Playwright driver組み立て完了: {driver_dir}")
    return driver_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Playwright driverを組み立てる")
    parser.add_argument("--dest", type=Path, default=None,
                        help=f"配置先ディレクトリ (default: {DEFAULT_DRIVER_DIR})")
    parser.add_argument("--version", default=PW_CLI_VERSION,
                        help=f"playwright-coreのバージョン (default: {PW_CLI_VERSION})")
    args = parser.parse_args()
    ensure_driver(args.dest, args.version)
