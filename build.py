#!/usr/bin/env python3
"""Build the Naukri Profile Manager into a standalone executable.

Usage:
    python build.py              # onedir (folder) — recommended
    python build.py --onefile    # single executable

NOTE: PyInstaller does NOT cross-compile. Build on Windows (for .exe),
macOS (for .app), and Linux separately, each on its own OS.
"""
import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "src" / "main.py"
NAME = "NaukriProfileManager"


def _httpcloak_lib() -> tuple[Path, str] | None:
    """Locate httpcloak's native shared library.

    httpcloak loads libhttpcloak-{os}-{arch}.so/.dll/.dylib at runtime by
    searching next to its package dir, so PyInstaller does NOT auto-bundle it.
    We find it in the installed package and return (source_path, dest_relpath).
    """
    import httpcloak

    pkg = Path(httpcloak.__file__).resolve().parent
    system = platform.system().lower()  # linux / darwin / windows
    machine = platform.machine().lower()
    arch = "amd64" if machine in ("x86_64", "amd64") else (
        "arm64" if machine in ("aarch64", "arm64") else machine
    )
    if system == "darwin":
        lib_name = f"libhttpcloak-darwin-{arch}.dylib"
    elif system == "windows":
        lib_name = f"libhttpcloak-windows-{arch}.dll"
    else:
        lib_name = f"libhttpcloak-linux-{arch}.so"

    for cand in (pkg / lib_name, pkg / "lib" / lib_name):
        if cand.exists():
            return cand, "httpcloak/lib"
    return None


def build(onefile: bool) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", NAME,
        "--paths", str(ROOT),  # make `src` importable for analysis
        str(ENTRY),
    ]
    if onefile:
        cmd.insert(3, "--onefile")

    lib = _httpcloak_lib()
    if lib:
        src, dest = lib
        sep = ";" if platform.system() == "Windows" else ":"
        cmd += ["--add-binary", f"{src}{sep}{dest}"]
        print(f"Bundling httpcloak binary: {src} -> {dest}")
    else:
        print("WARNING: could not find httpcloak native library to bundle.")

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    dist = ROOT / "dist" / (NAME + (".exe" if platform.system() == "Windows" else ""))
    print(f"\nBuild complete: {dist}")
    if not onefile:
        print("Distribution folder:", ROOT / "dist")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onefile", action="store_true",
        help="Build a single-file executable (slower startup) instead of a folder.",
    )
    args = parser.parse_args()

    if not shutil.which("pyinstaller") and not (Path(sys.prefix) / "bin" / "pyinstaller").exists():
        print("PyInstaller not found. Install with: pip install -r requirements.txt pyinstaller")
        return 1

    build(onefile=args.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())