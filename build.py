#!/usr/bin/env python3
"""Build the Naukri Profile Manager into a standalone executable.

Usage:
    python build.py                          # onedir (folder) — recommended
    python build.py --onefile                # single executable
    python build.py --onefile --version v0.2.0         # versioned single file
    python build.py --onefile --version v0.2.0 --versioned  # -> <name>-<ver>-<os>-<arch>

NOTE: PyInstaller does NOT cross-compile. Build on Windows (for .exe),
macOS (for .app), and Linux separately, each on its own OS.
"""
import argparse
import platform
import re
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


def _embed_fallback_version(version: str) -> None:
    """Pin the About-tab version in frozen builds.

    Frozen apps have no ``pyproject.toml``, so ``app_version()`` reads
    ``_FALLBACK_VERSION`` from ``src/core/version.py``. That source file must
    carry the version actually being built, otherwise the About tab shows a
    stale value (e.g. a v0.2.0 binary reporting 0.1.0). No-op when the value
    already matches, so local builds leave the working tree untouched.
    """
    cleaned = version.lstrip("v") or version
    path = ROOT / "src" / "core" / "version.py"
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r'(?m)^(_FALLBACK_VERSION\s*=\s*")[^"]+(")',
        rf"\g<1>{cleaned}\g<2>",
        text,
        count=1,
    )
    if n and new != text:
        path.write_text(new, encoding="utf-8")
        print(f"Pinned _FALLBACK_VERSION to {cleaned} in {path.name}")


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


def _pyside6_designer_dir() -> Path | None:
    """Return the Qt Designer plugin dir inside the active PySide6 package."""
    try:
        import PySide6
    except Exception:
        return None
    plugins = Path(PySide6.__file__).resolve().parent / "Qt" / "plugins" / "designer"
    return plugins if plugins.is_dir() else None


def build(*, onefile: bool, version: str, versioned: bool) -> Path:
    _embed_fallback_version(version)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", NAME,
        "--paths", str(ROOT),  # make `src` importable for analysis
        # PySide6's Qt6 shared libraries (PySide6/Qt/lib, versioned sonames)
        # and the shiboken binding loader are not reliably captured by the
        # default hooks; without these the packaged app dies at import with
        # "ImportError: DLL load failed while importing QtWidgets". This is
        # the officially recommended PySide6 bundling.
        "--collect-all", "PySide6",
        "--collect-all", "shiboken6",
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

        # Qt Designer plugin exclusion. --collect-all PySide6 copies every
        # binary under the PySide6 package, including
        # Qt/plugins/designer/libqwebengineview.so. On machines with a system
        # Qt install that plugin's ldd resolves WebEngine/WebChannel/QtPdf
        # (plus the Chromium FFmpeg codec tree) from /usr/lib64, and PyInstaller
        # drags ~200 MB of unused runtime libs into the app. Moving the dir OUT
        # of the PySide6 package (into this tempdir, same filesystem) keeps it
        # out of the collect; merely renaming it in place does not, since
        # --collect-all scans the whole package recursively. Restored after.
        designer = _pyside6_designer_dir()
        parked: Path | None = None
        if designer is not None:
            parked = Path(tmp) / "designer.__DISABLED__"
            designer.rename(parked)
            print(f"Parked Qt Designer plugin out of the bundle: {designer.name}")

        try:
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
        finally:
            if parked is not None and parked.is_dir() and designer is not None \
                    and not designer.exists():
                parked.rename(designer)
                print(f"Restored Qt Designer plugin: {designer.name}")

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