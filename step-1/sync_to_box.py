#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""
sync_to_box.py
==============
インターネットに接続された Windows (または Linux/macOS) 端末上で実行し、
Box 同期フォルダ内に制限環境用の uv ミラー一式を差分構築するスクリプト。

収集対象:
1. uv 本体バイナリ (Windows x86_64 / Linux x86_64) + バージョン情報 (version.txt)
2. uv が要求する正確なビルドタグの python-build-standalone ランタイム (Win / Linux)
3. 指定パッケージ群の Windows / Linux 両対応 Wheel (.whl) と全依存関係

特徴:
- 外部パッケージ依存ゼロ（Python 3.11+ 標準ライブラリのみで動作）
- 社内プロキシ & Zscaler (Windows OS 証明書ストア / カスタム CA 証明書) 対応
- ダウンロード済みファイルのスキップ（差分同期）と SHA256 ハッシュ検証
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


# ==============================================================================
# ネットワーク・Zscaler 証明書・プロキシ設定
# ==============================================================================
class NetworkClient:
    """プロキシと Zscaler (OS 証明書ストア / カスタム CA) に対応した HTTP クライアント"""

    def __init__(self, net_cfg: dict[str, Any]) -> None:
        self.use_system_certs: bool = bool(net_cfg.get("use_system_certs", True))
        self.ca_bundle: str = str(net_cfg.get("ca_bundle", "")).strip()
        self.https_proxy: str = str(net_cfg.get("https_proxy", "")).strip()
        self.http_proxy: str = str(net_cfg.get("http_proxy", "")).strip()
        self.no_proxy: str = str(net_cfg.get("no_proxy", "")).strip()
        self.verify_ssl: bool = bool(net_cfg.get("verify_ssl", True))

        self.ssl_context = self._build_ssl_context()
        self.opener = self._build_opener()

    def _build_ssl_context(self) -> ssl.SSLContext:
        if not self.verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

        ctx = ssl.create_default_context()

        # Windows 環境で Zscaler 等が OS 証明書ストアに入っている場合、ROOT と CA を明示ロード
        if self.use_system_certs and sys.platform == "win32" and hasattr(ssl, "enum_certificates"):
            pem_blocks: list[str] = []
            for store_name in ("ROOT", "CA"):
                try:
                    for cert_bytes, encoding, _trust in ssl.enum_certificates(store_name):
                        if encoding == "x509_asn":
                            pem_blocks.append(ssl.DER_cert_to_PEM_cert(cert_bytes))
                except Exception:
                    pass
            if pem_blocks:
                try:
                    ctx.load_verify_locations(cadata="\n".join(pem_blocks))
                except Exception:
                    pass

        # 明示的な CA バンドルファイル指定がある場合
        ca_file = (
            self.ca_bundle
            or os.environ.get("SSL_CERT_FILE", "")
            or os.environ.get("REQUESTS_CA_BUNDLE", "")
        )
        if ca_file:
            ca_path = Path(ca_file).expanduser().resolve()
            if not ca_path.is_file():
                raise FileNotFoundError(f"指定された CA 証明書ファイルが見つかりません: {ca_path}")
            ctx.load_verify_locations(cafile=str(ca_path))

        return ctx

    def _build_opener(self) -> urllib.request.OpenerDirector:
        proxies: dict[str, str] = {}
        if self.http_proxy:
            proxies["http"] = self.http_proxy
        if self.https_proxy:
            proxies["https"] = self.https_proxy

        # 空の場合は OS 環境変数または Windows レジストリのシステムプロキシを自動利用
        proxy_handler = (
            urllib.request.ProxyHandler(proxies)
            if proxies
            else urllib.request.ProxyHandler()
        )
        https_handler = urllib.request.HTTPSHandler(context=self.ssl_context)
        return urllib.request.build_opener(proxy_handler, https_handler)

    def build_uv_env(self) -> dict[str, str]:
        """uv サブプロセス実行用の環境変数を構築"""
        env = os.environ.copy()
        if self.use_system_certs:
            # OS ネイティブ証明書ストア(Zscaler等)を有効化
            env["UV_SYSTEM_CERTS"] = "true"
        if self.ca_bundle:
            env["SSL_CERT_FILE"] = str(Path(self.ca_bundle).expanduser().resolve())
        if self.https_proxy:
            env["HTTPS_PROXY"] = self.https_proxy
            env["https_proxy"] = self.https_proxy
        if self.http_proxy:
            env["HTTP_PROXY"] = self.http_proxy
            env["http_proxy"] = self.http_proxy
        if self.no_proxy:
            env["NO_PROXY"] = self.no_proxy
            env["no_proxy"] = self.no_proxy
        if not self.verify_ssl:
            env["UV_INSECURE_HOST"] = (
                "pypi.org files.pythonhosted.org github.com releases.astral.sh"
            )
        return env

    def resolve_redirect_url(self, url: str) -> str:
        """リダイレクト先の最終 URL を取得（GitHub Releases の latest 判定用）"""
        req = urllib.request.Request(url, headers={"User-Agent": "uv-offline-sync/1.0"})
        with self.opener.open(req, timeout=30) as resp:
            return resp.geturl()

    def get_json(self, url: str) -> Any:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "uv-offline-sync/1.0",
                "Accept": "application/vnd.github+json",
            },
        )
        with self.opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post_json(self, url: str, payload: Any) -> Any:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"User-Agent": "uv-offline-sync/1.0", "Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def download_file(
        self,
        url: str,
        dest: Path,
        expected_sha256: str | None = None,
    ) -> bool:
        """
        ファイルをダウンロードして dest に保存する。
        既に存在し（かつハッシュが一致し）ていれば False（スキップ）を返す。
        新規ダウンロードした場合は True を返す。
        """
        if dest.is_file():
            if expected_sha256:
                if verify_sha256(dest, expected_sha256):
                    return False
                print(f"  [再取得] ハッシュ不一致のため再取得します: {dest.name}")
            else:
                return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.with_suffix(dest.suffix + ".part")

        req = urllib.request.Request(url, headers={"User-Agent": "uv-offline-sync/1.0"})
        with self.opener.open(req, timeout=120) as resp, open(tmp_dest, "wb") as f:
            shutil.copyfileobj(resp, f, length=1024 * 256)

        if expected_sha256 and not verify_sha256(tmp_dest, expected_sha256):
            tmp_dest.unlink(missing_ok=True)
            raise ValueError(f"SHA256 ハッシュ検証に失敗しました: {dest.name}")

        tmp_dest.replace(dest)
        return True


def verify_sha256(file_path: Path, expected_hash: str) -> bool:
    clean_expected = expected_hash.removeprefix("sha256:").strip().lower()
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 512):
            h.update(chunk)
    return h.hexdigest().lower() == clean_expected


# ==============================================================================
# Step 1: uv 本体バイナリの取得とアップデート対応
# ==============================================================================
def get_local_uv_version(uv_bin: str) -> str:
    res = subprocess.run([uv_bin, "--version"], capture_output=True, text=True, check=True)
    # Output example: "uv 0.12.5 (Homebrew 2026-08-14 aarch64-apple-darwin)"
    parts = res.stdout.strip().split()
    if len(parts) >= 2:
        return parts[1]
    raise RuntimeError(f"uv のバージョン判定に失敗しました: {res.stdout}")


def get_latest_uv_version(net: NetworkClient) -> str:
    """GitHub Releases のリダイレクトから最新バージョン番号を取得（API レート制限回避）"""
    try:
        final_url = net.resolve_redirect_url("https://github.com/astral-sh/uv/releases/latest")
        # 例: https://github.com/astral-sh/uv/releases/tag/0.12.5
        if "/tag/" in final_url:
            return final_url.rsplit("/tag/", 1)[-1].strip().lstrip("v")
    except Exception:
        pass

    data = net.get_json("https://api.github.com/repos/astral-sh/uv/releases/latest")
    return str(data["tag_name"]).lstrip("v")


def sync_uv_binaries(
    cfg: dict[str, Any],
    net: NetworkClient,
    output_dir: Path,
    base_uv_bin: str,
) -> str:
    """
    uv 本体バイナリを mirror_data/uv/ にダウンロードする。
    Windows 環境で新しい uv を取得した場合は、以降のステップで使う uv 実行ファイルパスを返す。
    """
    uv_cfg = cfg.get("uv", {})
    target_ver_spec = str(uv_cfg.get("target_version", "latest")).strip()
    targets: list[str] = uv_cfg.get(
        "targets",
        ["x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu"],
    )

    if target_ver_spec == "local":
        version = get_local_uv_version(base_uv_bin)
    elif target_ver_spec == "latest":
        try:
            version = get_latest_uv_version(net)
        except Exception as e:
            print(f"  [警告] 最新版 uv のバージョン確認に失敗したためローカル版を使用します ({e})")
            version = get_local_uv_version(base_uv_bin)
    else:
        version = target_ver_spec.lstrip("v")

    print(f"\n[Step 1/3] uv 本体バイナリの同期 (対象バージョン: {version})")
    uv_dir = output_dir / "uv"
    ver_dir = uv_dir / version
    latest_dir = uv_dir / "latest"
    ver_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    for target in targets:
        ext = "zip" if "windows" in target else "tar.gz"
        filename = f"uv-{target}.{ext}"
        url = f"https://github.com/astral-sh/uv/releases/download/{version}/{filename}"
        dest = ver_dir / filename

        downloaded = net.download_file(url, dest)
        status = "ダウンロード完了" if downloaded else "スキップ (取得済)"
        print(f"  - {filename}: {status}")

        # latest ディレクトリにもコピーを配置（クライアントが固定 URL でアップデートできるようにする）
        latest_file = latest_dir / filename
        if downloaded or not latest_file.is_file():
            shutil.copy2(dest, latest_file)

    # クライアントがバージョン確認できる version.txt を出力
    (uv_dir / "version.txt").write_text(f"{version}\n", encoding="utf-8")
    (latest_dir / "version.txt").write_text(f"{version}\n", encoding="utf-8")

    # 実行環境と一致するアーカイブがあれば展開し、Step 2/3 でそのバージョンの uv を使用する
    active_uv_bin = base_uv_bin
    host_sys = sys.platform
    host_machine = platform.machine().lower()
    if host_sys == "win32" and host_machine in ("amd64", "x86_64"):
        win_zip = ver_dir / "uv-x86_64-pc-windows-msvc.zip"
        if win_zip.is_file():
            bin_cache = output_dir / ".bin" / version
            uv_exe = bin_cache / "uv.exe"
            if not uv_exe.is_file():
                bin_cache.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(win_zip, "r") as zf:
                    zf.extractall(bin_cache)
            if uv_exe.is_file():
                active_uv_bin = str(uv_exe)
                print(f"  -> 以降の解決には取得した uv ({version}) を使用します")

    return active_uv_bin


# ==============================================================================
# Step 2: Python ランタイム (python-build-standalone) の取得
# ==============================================================================
def sync_python_runtimes(
    cfg: dict[str, Any],
    net: NetworkClient,
    output_dir: Path,
    uv_bin: str,
) -> None:
    py_cfg = cfg.get("python", {})
    req_versions: list[str] = [str(v) for v in py_cfg.get("versions", ["3.11", "3.12", "3.13"])]
    req_platforms: list[dict[str, str]] = py_cfg.get(
        "platforms",
        [
            {"os": "windows", "arch": "x86_64", "libc": "none"},
            {"os": "linux", "arch": "x86_64", "libc": "gnu"},
        ],
    )

    print(f"\n[Step 2/3] Python ランタイム (python-build-standalone) の同期 (対象: {', '.join(req_versions)})")

    cmd = [
        uv_bin,
        "python",
        "list",
        "--all-platforms",
        "--all-arches",
        "--only-downloads",
        "--output-format",
        "json",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=net.build_uv_env())
    entries: list[dict[str, Any]] = json.loads(res.stdout)

    selected_urls: list[tuple[str, Path]] = []
    py_mirror_root = output_dir / "python"

    for entry in entries:
        if entry.get("implementation") != "cpython":
            continue
        if entry.get("variant", "default") != "default":
            continue

        # プラットフォーム一致判定
        plat_match = any(
            entry.get("os") == p.get("os")
            and entry.get("arch") == p.get("arch")
            and entry.get("libc", "none") == p.get("libc", "none")
            for p in req_platforms
        )
        if not plat_match:
            continue

        # バージョン一致判定 (例: "3.12" または "3.12.14")
        ver_str = str(entry.get("version", ""))
        vparts = entry.get("version_parts", {})
        major_minor = f"{vparts.get('major')}.{vparts.get('minor')}"
        if ver_str not in req_versions and major_minor not in req_versions:
            continue

        url = str(entry.get("url", ""))
        if not url:
            continue

        # URL 例:
        # https://releases.astral.sh/github/python-build-standalone/releases/download/20260814/cpython-3.12.14%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
        parsed = urllib.parse.urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            continue
        release_tag = path_parts[-2]
        raw_filename = urllib.parse.unquote(path_parts[-1])

        dest = py_mirror_root / release_tag / raw_filename
        selected_urls.append((url, dest))

    if not selected_urls:
        print("  [警告] 条件に一致する Python ランタイムが見つかりませんでした。")
        return

    for url, dest in selected_urls:
        downloaded = net.download_file(url, dest)
        status = "ダウンロード完了" if downloaded else "スキップ (取得済)"
        print(f"  - {dest.parent.name}/{dest.name}: {status}")


# ==============================================================================
# Step 3: Windows / Linux 両用 Wheel の解決・一括ダウンロード
# ==============================================================================
def parse_requirements_from_files(files: list[str]) -> list[str]:
    reqs: list[str] = []
    for file_str in files:
        p = Path(file_str).expanduser().resolve()
        if not p.is_file():
            print(f"  [警告] 指定された要件ファイルが見つかりません: {p}")
            continue
        if p.name == "pyproject.toml":
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            deps = data.get("project", {}).get("dependencies", [])
            reqs.extend(deps)
            opt_deps = data.get("project", {}).get("optional-dependencies", {})
            for group_deps in opt_deps.values():
                reqs.extend(group_deps)
            dependency_groups = data.get("dependency-groups", {})
            for group_deps in dependency_groups.values():
                reqs.extend(d for d in group_deps if isinstance(d, str))
        else:
            # requirements.txt 形式
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line and not line.startswith("-"):
                    reqs.append(line)
    return reqs


def is_wheel_compatible(
    filename: str,
    py_versions: list[str],
    platforms: list[dict[str, str]],
) -> bool:
    """
    PEP 427 Wheel ファイル名を解析し、対象 Python バージョンおよび対象 OS/Arch に必要か判定する。
    """
    if not filename.endswith(".whl"):
        return False
    stem = filename[:-4]
    parts = stem.rsplit("-", 3)
    if len(parts) < 4:
        return False
    _, py_tag, abi_tag, plat_tag = parts

    # Free-threaded (cp313t / cp314t) は通常環境では除外
    if re.search(r"cp3\d+t", abi_tag):
        return False

    # 1. プラットフォーム判定
    plat_ok = False
    if "any" in plat_tag:
        plat_ok = True
    else:
        for p in platforms:
            os_name = p.get("os")
            arch = p.get("arch")
            libc = p.get("libc", "none")
            if os_name == "windows" and arch == "x86_64" and "win_amd64" in plat_tag:
                plat_ok = True
            elif os_name == "linux" and arch == "x86_64":
                if libc == "gnu" and "linux_x86_64" in plat_tag and "musllinux" not in plat_tag:
                    plat_ok = True
                elif libc == "musl" and "musllinux" in plat_tag and "x86_64" in plat_tag:
                    plat_ok = True
            elif os_name == "linux" and arch == "aarch64":
                if libc == "gnu" and "linux_aarch64" in plat_tag and "musllinux" not in plat_tag:
                    plat_ok = True
    if not plat_ok:
        return False

    # 2. Python / ABI タグ判定
    minor_nums = []
    for v in py_versions:
        m = re.match(r"^3\.(\d+)", v)
        if m:
            minor_nums.append(int(m.group(1)))

    # 純粋 Python (py3-none-any 等)
    if abi_tag == "none" and ("py3" in py_tag or "py2" in py_tag):
        return True

    # 特定 CPython バージョン向け (cp311, cp312, cp313 等)
    for minor in minor_nums:
        if f"cp3{minor}" in py_tag or f"py3{minor}" in py_tag:
            return True

    # Stable ABI (abi3: 例 cp38-abi3 は Python 3.8 以降すべてで動作)
    if "abi3" in abi_tag:
        abi_match = re.search(r"cp3(\d+)", py_tag)
        if abi_match:
            abi_min = int(abi_match.group(1))
            if any(m >= abi_min for m in minor_nums):
                return True
        else:
            return True

    return False


def build_uv_environment_markers(platforms: list[dict[str, str]]) -> list[str]:
    markers: list[str] = []
    for p in platforms:
        os_name = p.get("os")
        arch = p.get("arch")
        if os_name == "windows" and arch == "x86_64":
            markers.append("sys_platform == 'win32' and platform_machine == 'AMD64'")
        elif os_name == "linux" and arch == "x86_64":
            markers.append("sys_platform == 'linux' and platform_machine == 'x86_64'")
        elif os_name == "linux" and arch == "aarch64":
            markers.append("sys_platform == 'linux' and platform_machine == 'aarch64'")
    return markers


def audit_packages(
    cfg: dict[str, Any],
    net: NetworkClient,
    packages: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    """uv.lock の解決結果を OSV (osv.dev) に照会し、既知の脆弱性を報告する (pip-audit 相当)"""
    audit_cfg = cfg.get("audit", {})
    if not audit_cfg.get("enabled", True):
        return
    ignore_ids = {str(i) for i in audit_cfg.get("ignore_ids", [])}
    fail_on_vuln = bool(audit_cfg.get("fail_on_vulnerability", False))

    targets = [
        (p["name"], p["version"])
        for p in packages
        if p.get("name") != "offline-wheel-collector" and p.get("version")
        and "registry" in p.get("source", {})
    ]
    print(f"\n[Audit] 脆弱性チェック (OSV): {len(targets)} パッケージ")
    queries = [
        {"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in targets
    ]
    try:
        ids_per_pkg: list[list[str]] = []
        for i in range(0, len(queries), 500):
            res = net.post_json(
                "https://api.osv.dev/v1/querybatch", {"queries": queries[i : i + 500]}
            )
            ids_per_pkg += [[v["id"] for v in r.get("vulns", [])] for r in res["results"]]

        findings: list[dict[str, Any]] = []
        for (name, ver), ids in zip(targets, ids_per_pkg):
            for vid in ids:
                detail = net.get_json(f"https://api.osv.dev/v1/vulns/{vid}")
                aliases = {vid, *detail.get("aliases", [])}
                if aliases & ignore_ids:
                    continue
                fixed = sorted(
                    {
                        e["fixed"]
                        for a in detail.get("affected", [])
                        if a.get("package", {}).get("name", "").lower().replace("_", "-") == name
                        for r in a.get("ranges", [])
                        for e in r.get("events", [])
                        if "fixed" in e
                    }
                )
                findings.append(
                    {
                        "package": name,
                        "version": ver,
                        "id": vid,
                        "aliases": sorted(aliases - {vid}),
                        "fixed_in": fixed,
                        "summary": detail.get("summary", ""),
                    }
                )
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        msg = f"  [警告] 脆弱性チェックに失敗しました: {e}"
        if fail_on_vuln:
            sys.exit(msg)
        print(msg)
        return

    (output_dir / "audit_report.json").write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not findings:
        print("  -> 既知の脆弱性は見つかりませんでした")
        return
    for f in findings:
        fix = ", ".join(f["fixed_in"]) or "修正版なし"
        print(f"  [脆弱性] {f['package']}=={f['version']}  {f['id']}  (修正版: {fix})")
        if f["summary"]:
            print(f"      {f['summary']}")
    print(f"  -> {len(findings)} 件検出 (詳細: {output_dir / 'audit_report.json'})")
    if fail_on_vuln:
        sys.exit("エラー: 脆弱性が検出されたため中断します ([audit] fail_on_vulnerability = true)")


def sync_wheels(
    cfg: dict[str, Any],
    net: NetworkClient,
    output_dir: Path,
    uv_bin: str,
    max_workers: int,
) -> None:
    pkg_cfg = cfg.get("packages", {})
    include_pkgs: list[str] = list(pkg_cfg.get("include", []))
    req_files: list[str] = list(pkg_cfg.get("requirement_files", []))
    all_reqs = include_pkgs + parse_requirements_from_files(req_files)

    if not all_reqs:
        print("\n[Step 3/3] パッケージ指定がないため Wheel 同期をスキップします")
        return

    py_cfg = cfg.get("python", {})
    py_versions: list[str] = [str(v) for v in py_cfg.get("versions", ["3.11", "3.12", "3.13"])]
    platforms: list[dict[str, str]] = py_cfg.get(
        "platforms",
        [
            {"os": "windows", "arch": "x86_64", "libc": "none"},
            {"os": "linux", "arch": "x86_64", "libc": "gnu"},
        ],
    )

    # 最小 Python バージョンを算出 (例: ">=3.11")
    min_minor = min(int(v.split(".")[1]) for v in py_versions if "." in v)
    requires_python = f">=3.{min_minor}"
    env_markers = build_uv_environment_markers(platforms)

    print(
        f"\n[Step 3/3] Windows / Linux 両用 Wheel の解決と同期 "
        f"(要求パッケージ数: {len(all_reqs)}, Python {requires_python})"
    )

    wheels_dir = output_dir / "wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)

    # 一時ディレクトリで uv lock を実行し、全プラットフォーム・全バージョンの Wheel URL とハッシュを取得
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        pyproject_content = {
            "project": {
                "name": "offline-wheel-collector",
                "version": "0.1.0",
                "requires-python": requires_python,
                "dependencies": all_reqs,
            },
            "tool": {
                "uv": {
                    "environments": env_markers,
                }
            },
        }
        # pyproject.toml を書き出し
        deps_toml = ",\n    ".join(json.dumps(r) for r in all_reqs)
        envs_toml = ",\n    ".join(json.dumps(m) for m in env_markers)
        pyproject_text = f"""[project]
name = "offline-wheel-collector"
version = "0.1.0"
requires-python = "{requires_python}"
dependencies = [
    {deps_toml}
]

[tool.uv]
environments = [
    {envs_toml}
]
"""
        (tmp_path / "pyproject.toml").write_text(pyproject_text, encoding="utf-8")

        cmd = [uv_bin, "lock", "--directory", str(tmp_path)]
        if net.use_system_certs:
            cmd.append("--system-certs")
        subprocess.run(cmd, check=True, env=net.build_uv_env())

        lock_data = tomllib.loads((tmp_path / "uv.lock").read_text(encoding="utf-8"))

    packages = lock_data.get("package", [])
    audit_packages(cfg, net, packages, output_dir)
    download_tasks: dict[str, tuple[str, Path, str | None]] = {}

    for pkg in packages:
        pkg_name = pkg.get("name")
        if pkg_name == "offline-wheel-collector":
            continue

        wheels = pkg.get("wheels", [])
        matched_any_wheel = False
        for whl in wheels:
            url = str(whl.get("url", ""))
            if not url:
                continue
            filename = urllib.parse.unquote(url.rsplit("/", 1)[-1])
            if is_wheel_compatible(filename, py_versions, platforms):
                matched_any_wheel = True
                sha256_hash = whl.get("hash")
                download_tasks[filename] = (url, wheels_dir / filename, sha256_hash)

        # 万が一 Wheel が提供されていない純粋 sdist パッケージの場合は sdist (.tar.gz) を取得
        if not matched_any_wheel and "sdist" in pkg:
            sdist = pkg["sdist"]
            url = str(sdist.get("url", ""))
            if url:
                filename = urllib.parse.unquote(url.rsplit("/", 1)[-1])
                sha256_hash = sdist.get("hash")
                download_tasks[filename] = (url, wheels_dir / filename, sha256_hash)

    print(f"  -> 解決完了: 合計 {len(download_tasks)} 個のパッケージファイル (Win/Linux 両対応) を確認します")

    downloaded_count = 0
    skipped_count = 0

    def _worker(item: tuple[str, tuple[str, Path, str | None]]) -> tuple[str, bool]:
        fname, (u, dst, h) = item
        is_new = net.download_file(u, dst, expected_sha256=h)
        return fname, is_new

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, item) for item in sorted(download_tasks.items())]
        for fut in concurrent.futures.as_completed(futures):
            fname, is_new = fut.result()
            if is_new:
                downloaded_count += 1
                print(f"  [新規取得] {fname}")
            else:
                skipped_count += 1

    print(
        f"  -> Wheel 同期完了: 新規ダウンロード {downloaded_count} 件 / "
        f"スキップ(取得済) {skipped_count} 件 (保存先: {wheels_dir})"
    )


# ==============================================================================
# エントリポイント
# ==============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="インターネット環境で uv 本体・Python ランタイム・Win/Linux 両用 Wheel を Box 用フォルダへ収集します。"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.toml",
        help="設定ファイル (config.toml) のパス (デフォルト: config.toml)",
    )
    parser.add_argument(
        "--uv-bin",
        default="uv",
        help="使用する uv コマンドのパス (デフォルト: uv)",
    )
    parser.add_argument(
        "--skip-uv",
        action="store_true",
        help="Step 1 (uv 本体バイナリの取得) をスキップする",
    )
    parser.add_argument(
        "--skip-python",
        action="store_true",
        help="Step 2 (Python ランタイムの取得) をスキップする",
    )
    parser.add_argument(
        "--skip-wheels",
        action="store_true",
        help="Step 3 (Wheel の取得) をスキップする",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        sys.exit(f"エラー: 設定ファイルが見つかりません: {config_path}")

    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    mirror_cfg = cfg.get("mirror", {})
    raw_output_dir = str(mirror_cfg.get("output_dir", "./mirror_data"))
    output_dir = (config_path.parent / raw_output_dir).resolve()
    max_workers = int(mirror_cfg.get("max_workers", 4))

    print("==================================================================")
    print(" uv オフラインミラー同期ツール (Box 連携用)")
    print(f" 設定ファイル : {config_path}")
    print(f" 出力先フォルダ: {output_dir}")
    print("==================================================================")

    output_dir.mkdir(parents=True, exist_ok=True)
    net = NetworkClient(cfg.get("network", {}))

    active_uv_bin = args.uv_bin
    if not args.skip_uv:
        active_uv_bin = sync_uv_binaries(cfg, net, output_dir, args.uv_bin)

    if not args.skip_python:
        sync_python_runtimes(cfg, net, output_dir, active_uv_bin)

    if not args.skip_wheels:
        sync_wheels(cfg, net, output_dir, active_uv_bin, max_workers=max_workers)

    print("\n[完了] すべての同期処理が正常に完了しました！")


if __name__ == "__main__":
    main()
