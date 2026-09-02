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
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "src" / "main.py"
NAME = "NaukriProfileManager"

# Adapted import so this helper also works when run from a frozen toolchain.
sys.path.insert(0, str(ROOT))
from src.core.version import DEVELOPER, app_version  # noqa: E402


def _version_info(path: Path) -> None:
    """Write a Windows VERSIONINFO file for --version-file."""
    version = app_version()
    parts = (version.split(".") + ["0", "0"])[:4]
    while len(parts) < 4:
        parts.append("0")
    major, minor, patch, build = (str(p) for p in parts)
    four = ", ".join([major, minor, patch, build])
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({four}),
    prodvers=({four}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{DEVELOPER}'),
        StringStruct('FileDescription', 'Naukri Profile Manager'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'NaukriProfileManager'),
        StringStruct('LegalCopyright', 'Copyright (c) {DEVELOPER}'),
        StringStruct('OriginalFilename', 'NaukriProfileManager'),
        StringStruct('ProductName', 'Naukri Profile Manager'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


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
    else:
        cmd.insert(3, "--onedir")

    system = platform.system()

    # Embed app version metadata into the Windows executable / macOS bundle.
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        version_info = Path(tmp) / "version_info.txt"
        _version_info(version_info)
        cmd += ["--version-file", str(version_info)]

        # Optional app icon (root-level app.ico / app.icns / app.png).
        icon = _find_icon(system)
        if icon:
            cmd += ["--icon", str(icon)]
            print(f"Using icon: {icon}")
        else:
            print("No app.ico/app.icns/app.png found; skipping --icon.")

        lib = _httpcloak_lib()
        if lib:
            src, dest = lib
            sep = ";" if system == "Windows" else ":"
            cmd += ["--add-binary", f"{src}{sep}{dest}"]
            print(f"Bundling httpcloak binary: {src} -> {dest}")
        else:
            print("WARNING: could not find httpcloak native library to bundle.")

        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=ROOT)

    dist = ROOT / "dist" / (NAME + (".exe" if system == "Windows" else ""))
    print(f"\nBuild complete: {dist}")
    if not onefile:
        print("Distribution folder:", ROOT / "dist")


def _find_icon(system: str) -> Path | None:
    """Return the best matching app icon for the current OS, if present."""
    if system == "Windows":
        names = ("app.ico", "app.png")
    elif system == "Darwin":
        names = ("app.icns", "app.png")
    else:
        names = ("app.png", "app.ico")
    for name in names:
        cand = ROOT / name
        if cand.exists():
            return cand
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onefile", action="store_true",
        help="Build a single-file executable (slower startup) instead of a folder.",
    )
    args = parser.parse_args()

    if not shutil.which("pyinstaller") and not (Path(sys.prefix) / "bin" / "pyinstaller").exists():
        print("PyInstaller not found. Installing pyinstaller ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )

    build(onefile=args.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())