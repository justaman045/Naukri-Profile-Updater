#!/usr/bin/env python3
"""Build the Naukri Profile Manager into a standalone executable.

Usage:
    python build.py                          # onedir (folder) — recommended
    python build.py --onefile                # single executable
    python build.py --onefile --version v0.1.0         # versioned single file
    python build.py --onefile --version v0.1.0 --versioned  # -> <name>-<ver>-<os>-<arch>

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


def _version_info(path: Path, version: str) -> None:
    """Write a Windows VERSIONINFO file for --version-file.

    VERSIONINFO requires a strictly-numeric, 4-part file/product version
    (PyInstaller evals the file as Python, so non-numeric fields crash with a
    NameError). Accept any input like "v0.1.0" or even a branch name and
    normalize it to four integers, defaulting missing parts to 0.
    """
    version = version.lstrip("v")
    digits = [p for p in version.split(".") if p.isdigit()]
    parts = (digits + ["0", "0", "0", "0"])[:4]
    four = ", ".join(parts)
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


def build(*, onefile: bool, version: str, versioned: bool) -> Path:
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
        _version_info(version_info, version)
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
    if onefile and versioned:
        dist = _rename_versioned(dist, version)
    print(f"\nBuild complete: {dist}")
    if not onefile:
        print("Distribution folder:", ROOT / "dist")
    return dist


def _rename_versioned(dist: Path, version: str) -> Path:
    """Rename a onefile artifact to `Name-<ver>-<os>-<arch>`."""
    cleaned = version.lstrip("v")
    system = platform.system().lower()
    machine = platform.machine().lower()
    _OS_ALIASES = {"darwin": "macos", "windows": "windows", "linux": "linux"}
    os_label = _OS_ALIASES.get(system, system)
    arch = "x86_64" if machine in ("x86_64", "amd64") else (
        "arm64" if machine in ("aarch64", "arm64") else machine
    )
    suffix = dist.suffix  # e.g. '.exe' or ''
    stem = dist.stem  # 'NaukriProfileManager'
    new_name = f"{stem}-{cleaned}-{os_label}-{arch}{suffix}"
    new_path = dist.with_name(new_name)
    dist.rename(new_path)
    return new_path


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
    parser.add_argument(
        "--versioned", action="store_true",
        help="Rename the onefile artifact to Name-<version>-<os>-<arch> (implies --onefile).",
    )
    parser.add_argument(
        "--version", default=None,
        help="Version to embed/rename with (default: from pyproject.toml).",
    )
    args = parser.parse_args()

    if not shutil.which("pyinstaller") and not (Path(sys.prefix) / "bin" / "pyinstaller").exists():
        print("PyInstaller not found. Installing pyinstaller ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )

    onefile = args.onefile or args.versioned
    version = args.version or app_version()
    build(onefile=onefile, version=version, versioned=args.versioned)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())