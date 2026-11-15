"""Doctor subcommand: detect, report, and install heavy deps (wget, chromium)."""

import fcntl
import glob
import hashlib
import logging
import os
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

import click

from dograpper.utils.dep_resolver import (
    USER_BIN_DIR,
    USER_BROWSER_DIR,
    ensure_dirs,
    resolve_browser_dir,
    resolve_wget,
)

logger = logging.getLogger(__name__)

BUSYBOX_WGET_URL = (
    "https://github.com/lorenzoervedosa/dograpper/releases/download/"
    "v0.0.0-tooling/busybox-wget-x86_64"
)
# SHA256 of the v0.0.0-tooling busybox-wget-x86_64 asset.
BUSYBOX_WGET_SHA256 = "6e123e7f3202a8c1e9b1f94d8941580a25135382b99e8d3e34fb858bba311348"

LIB_TO_PKG = {
    "libnss3.so": "libnss3",
    "libatk-bridge-2.0.so": "libatk-bridge2.0-0",
    "libdrm.so": "libdrm2",
    "libxkbcommon.so": "libxkbcommon0",
    "libgbm.so": "libgbm1",
    "libasound.so": "libasound2",
    "libatk-1.0.so": "libatk1.0-0",
    "libcups.so": "libcups2",
}


def _find_chromium() -> str | None:
    pattern = str(USER_BROWSER_DIR / "chromium-*" / "chrome-linux" / "chrome")
    matches = glob.glob(pattern)
    for m in matches:
        if os.access(m, os.X_OK):
            return m
    return None


def _get_wget_info() -> tuple[str, str]:
    """Return (path_or_MISSING, version_or_dash)."""
    path = resolve_wget()
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            first_line = (result.stdout or result.stderr or "").splitlines()[0] if (result.stdout or result.stderr) else ""
            version = first_line.strip() or "ok"
            return path, version
    except Exception:
        pass
    return "MISSING", "---"


def _get_chromium_info() -> tuple[str, str]:
    """Return (path_or_MISSING, version_or_dash)."""
    path = _find_chromium()
    if path:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = (result.stdout or "").strip()
            return path, first_line or "ok"
        except Exception:
            return path, "ok"
    return "MISSING", "---"


def _detect_distro() -> str:
    """Return package manager: apt, dnf, or pacman."""
    try:
        with open("/etc/os-release", errors="replace") as f:
            content = f.read()
        for line in content.splitlines():
            if line.startswith("ID="):
                distro_id = line.split("=", 1)[1].strip().strip('"').lower()
                if distro_id in ("ubuntu", "debian", "linuxmint", "pop"):
                    return "apt"
                if distro_id in ("fedora", "rhel", "centos", "rocky", "alma"):
                    return "dnf"
                if distro_id == "arch":
                    return "pacman"
    except OSError:
        pass
    return "apt"


def _install_wget(force: bool) -> bool:
    """Download busybox-wget to USER_BIN_DIR/wget. Returns True if installed."""
    dest = USER_BIN_DIR / "wget"
    if dest.exists() and os.access(dest, os.X_OK) and not force:
        click.echo("wget: ok, nothing to do")
        return False

    click.echo(f"Downloading wget from {BUSYBOX_WGET_URL} ...")
    try:
        with urllib.request.urlopen(BUSYBOX_WGET_URL) as resp:  # noqa: S310
            data = resp.read()
    except Exception as e:
        click.echo(f"ERROR: failed to download wget: {e}", err=True)
        sys.exit(1)

    if len(BUSYBOX_WGET_SHA256) != 64 or not all(c in "0123456789abcdef" for c in BUSYBOX_WGET_SHA256):
        click.echo(
            "ERROR: BUSYBOX_WGET_SHA256 is not a valid 64-char hex digest. "
            "This build is unsafe; aborting wget install. "
            "Pin the real SHA256 in commands/doctor.py before release.",
            err=True,
        )
        sys.exit(1)
    digest = hashlib.sha256(data).hexdigest()
    if digest != BUSYBOX_WGET_SHA256:
        click.echo(
            f"ERROR: SHA256 mismatch for wget binary. Got {digest}, expected {BUSYBOX_WGET_SHA256}",
            err=True,
        )
        sys.exit(1)

    ensure_dirs()
    dest.write_bytes(data)
    dest.chmod(0o755)
    click.echo(f"wget installed to {dest}")
    return True


def _install_chromium() -> None:
    """Install chromium via playwright public API with private fallback."""
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = resolve_browser_dir()
    try:
        from playwright.__main__ import main as pw_main
        pw_main(["install", "chromium"])
    except (ImportError, AttributeError) as e:
        logger.warning(
            f"public playwright API unavailable: {e}; falling back to private _impl._driver"
        )
        try:
            from playwright._impl._driver import install as _private_install
            _private_install(["chromium"])
        except Exception as e2:
            click.echo(f"ERROR: failed to install chromium: {e2}", err=True)
            sys.exit(1)

    # PyInstaller Node driver exec-bit fix — idempotent.
    if hasattr(sys, "_MEIPASS"):
        driver_root = Path(sys._MEIPASS) / "playwright" / "driver"
        if driver_root.exists():
            for f in driver_root.rglob("*"):
                if f.is_file():
                    f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@click.command("doctor")
@click.option("--install", "do_install", is_flag=True, default=False,
              help="Download and install missing dependencies (wget, chromium).")
@click.option("--force", is_flag=True, default=False,
              help="Re-install dependencies even if already present.")
@click.option("--check-system-libs", "check_system_libs", is_flag=True, default=False,
              help="Check system libraries required by chromium and suggest install command.")
def doctor(do_install: bool, force: bool, check_system_libs: bool) -> None:
    """Detect, report, and install heavy dependencies (wget, chromium).

    Without flags: prints status table and exits 0 (all OK) or 1 (any MISSING).

    \b
    Examples:
      dograpper doctor
      dograpper doctor --install
      dograpper doctor --install --force
      dograpper doctor --check-system-libs
    """
    if check_system_libs:
        chromium_path = _find_chromium()
        if not chromium_path:
            click.echo(
                "chromium not installed; run `dograpper doctor --install` first",
                err=True,
            )
            sys.exit(3)

        try:
            ldd_output = subprocess.check_output(
                ["ldd", chromium_path],
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
        except subprocess.CalledProcessError as e:
            ldd_output = e.output or ""
        except FileNotFoundError:
            click.echo("ERROR: ldd not found on this system.", err=True)
            sys.exit(1)

        missing_libs = []
        for line in ldd_output.splitlines():
            if "=> not found" in line:
                so_name = line.strip().split()[0]
                # Match against LIB_TO_PKG by prefix (strip version suffix)
                for lib_prefix, pkg in LIB_TO_PKG.items():
                    if so_name.startswith(lib_prefix.rstrip(".so").rstrip("0123456789.")):
                        if pkg not in missing_libs:
                            missing_libs.append(pkg)
                        break

        if not missing_libs:
            click.echo("All required system libraries are present.")
            sys.exit(0)

        pkg_manager = _detect_distro()
        if pkg_manager == "apt":
            cmd = f"sudo apt install -y {' '.join(missing_libs)}"
        elif pkg_manager == "dnf":
            cmd = f"sudo dnf install -y {' '.join(missing_libs)}"
        else:
            cmd = f"sudo pacman -S {' '.join(missing_libs)}"

        click.echo(f"Missing system libraries detected. Run:\n  {cmd}")
        sys.exit(2)

    if do_install:
        ensure_dirs()
        lock_path = USER_BIN_DIR / ".lock"
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            click.echo("another doctor --install in progress", err=True)
            sys.exit(4)

        try:
            wget_path, _ = _get_wget_info()
            wget_missing = wget_path == "MISSING"
            chromium_path = _find_chromium()
            chromium_missing = chromium_path is None

            if not wget_missing and not chromium_missing and not force:
                click.echo("ok, nothing to do")
                return

            if wget_missing or force:
                _install_wget(force)

            if chromium_missing or force:
                click.echo("Installing chromium via playwright...")
                _install_chromium()
                click.echo("chromium installed.")
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass
        return

    # Default: status table
    wget_path, wget_version = _get_wget_info()
    chromium_path_str, chromium_version = _get_chromium_info()

    click.echo(f"{'WGET':<10} {wget_path:<50} {wget_version}")
    click.echo(f"{'CHROMIUM':<10} {chromium_path_str:<50} {chromium_version}")

    if wget_path == "MISSING" or chromium_path_str == "MISSING":
        sys.exit(1)
