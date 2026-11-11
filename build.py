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
import os
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


def _playwright_browser() -> tuple[Path, Path] | None:
    """Locate Playwright's Chromium browser binary for bundling.

    PyInstaller's ``--collect-all playwright`` collects the Python package but
    not the downloaded Chromium executable (which lives in the ms-playwright
    cache). Without it, Playwright cannot launch a browser in the frozen app,
    so auto-capture of the Naukri session cookie would fail.

    Returns ``(browser_dir, bundle_source)`` where ``browser_dir`` is the
    directory containing the Chromium executable, or None when not found.
    """
    import os

    browsers_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
    if not browsers_root.is_dir():
        return None

    # Look for a Chromium installation.
    for candidate in sorted(browsers_root.iterdir()):
        if not candidate.is_dir():
            continue
        if not candidate.name.startswith("chromium"):
            continue
        # Find the chrome executable inside.
        for exec_name in ("chrome", "chrome.exe", "Chromium"):
            exec_path = candidate / exec_name
            if exec_path.is_file():
                return candidate, candidate
        # macOS app bundle.
        app_bundle = candidate / "chrome-mac" / "Chromium.app"
        if app_bundle.is_dir():
            return app_bundle, app_bundle

    return None


def _httpcloak_lib() -> tuple[Path, Path]:
    """Locate httpcloak's native shared library.

    Returns ``(lib_file, bundle_source)``:

    * ``lib_file`` — the platform-specific shared library itself;
    * ``bundle_source`` — what to hand to ``--add-binary``. Usually the whole
      ``lib`` directory, so companion libraries that ship beside it (the
      MinGW runtime ``libgcc_s_seh-1.dll`` and the OpenSSL DLLs that the
      Windows build needs) travel with the bundle instead of being resolved
      from the user's machine.

    Raises ``SystemExit`` when the library cannot be found. Failing the build
    is deliberate: a bundle without it builds cleanly, passes CI, and then
    dies on the user's machine with "Could not find httpcloak library" — the
    single most confusing failure this project has shipped.
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

    lib_dir = pkg / "lib"
    searched = [lib_dir, pkg]

    for directory in searched:
        candidate = directory / lib_name
        if candidate.is_file():
            return candidate, (lib_dir if directory == lib_dir else candidate)
        # Tolerate an upstream rename or a version suffix.
        stem, ext = os.path.splitext(lib_name)
        for pattern in (f"{stem}*{ext}", f"libhttpcloak*{ext}"):
            matches = sorted(p for p in directory.glob(pattern) if p.is_file())
            if matches:
                return matches[0], (lib_dir if directory == lib_dir else matches[0])

    version = getattr(httpcloak, "__version__", "unknown")
    raise SystemExit(
        "ERROR: could not find httpcloak's native library.\n"
        f"  expected file : {lib_name}\n"
        f"  httpcloak     : {version}\n"
        f"  searched      : {', '.join(str(d) for d in searched)}\n"
        "The resulting bundle would fail at start-up on every user's machine.\n"
        "Refusing to build — install a matching httpcloak version or update "
        "the expected library name in build.py."
    )


def _ensure_companion_dlls(bundle_source: Path) -> None:
    """Make sure MinGW companion DLLs travel with the httpcloak bundle.

    httpcloak's Windows build is linked against MinGW and needs
    ``libwinpthread-1.dll`` (and ``libgcc_s_seh-1.dll``) at runtime. The
    httpcloak wheel ships ``libgcc_s_seh-1.dll`` but not ``libwinpthread-1.dll``,
    so a clean machine without MinGW on PATH fails to load the library. Copy any
    missing companion from PATH / a known MinGW location into the bundle dir.
    """
    required = ("libwinpthread-1.dll",)
    search_dirs: list[Path] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry)
        if candidate.is_dir():
            search_dirs.append(candidate)
    for candidate in (
        Path("C:/Program Files/Git/mingw64/bin"),
        Path("C:/msys64/mingw64/bin"),
        Path("C:/msys64/usr/bin"),
        Path("C:/mingw64/bin"),
    ):
        if candidate.is_dir():
            search_dirs.append(candidate)

    for name in required:
        target = bundle_source / name
        if target.is_file():
            continue
        found: Path | None = None
        for directory in search_dirs:
            candidate = directory / name
            if candidate.is_file():
                found = candidate
                break
        if found is None:
            raise SystemExit(
                "ERROR: required companion DLL not found: "
                f"{name}. Install MinGW (or Git for Windows) or place the DLL "
                "on PATH, then rebuild."
            )
        shutil.copy2(found, target)
        print(f"Copied companion DLL: {found} -> {target}")


def _verify_artifact(artifact: Path) -> None:
    """Fail the build when the native library is missing from the artifact.

    A bundle without httpcloak's native library builds fine and dies on the
    user's machine with "Could not find httpcloak library". Checking the
    artifact we just produced turns that into a red build instead.
    """
    verifier = ROOT / "tools" / "verify_bundle.py"
    if not verifier.is_file():
        print(f"WARNING: {verifier} not found — skipping bundle verification.")
        return
    print("Verifying bundle contents ...")
    result = subprocess.run([sys.executable, str(verifier), str(artifact)], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: bundle verification failed for {artifact}. Refusing to "
            "publish an artifact that would fail at start-up."
        )


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
        # Playwright (python package) is needed by login_via_browser.py which
        # the frozen build runs to auto-capture the Naukri session cookie.
        "--collect-all", "playwright",
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

            lib_file, bundle_source = _httpcloak_lib()
            bundle_source_path = Path(bundle_source)
            if system == "Windows" and bundle_source_path.is_dir():
                _ensure_companion_dlls(bundle_source_path)
            sep = ";" if system == "Windows" else ":"
            cmd += ["--add-binary", f"{bundle_source}{sep}httpcloak/lib"]
            print(f"Bundling httpcloak binary: {lib_file} -> httpcloak/lib")

            # Bundle Playwright's Chromium browser so frozen builds can launch
            # a real browser to auto-capture the Naukri session cookie.
            browser = _playwright_browser()
            if browser is not None:
                browser_dir, bundle_source = browser
                cmd += ["--add-data", f"{bundle_source}{sep}playwright-browsers"]
                print(f"Bundling Playwright browser: {browser_dir} -> playwright-browsers")
            else:
                print("WARNING: Playwright Chromium browser not found. "
                      "Auto-capture in frozen builds will fail unless the "
                      "browser is available on the target machine.")

            # Bundle the browser-login helper so frozen builds can auto-capture
            # the Naukri session cookie. It is referenced at runtime from
            # _MEIPASS (frozen) or ROOT (source checkout).
            login_helper = ROOT / "login_via_browser.py"
            cmd += ["--add-data", f"{login_helper}{sep}."]
            print(f"Bundling login helper: {login_helper}")

            print("Running:", " ".join(cmd))
            subprocess.run(cmd, check=True, cwd=ROOT)
        finally:
            if parked is not None and parked.is_dir() and designer is not None \
                    and not designer.exists():
                parked.rename(designer)
                print(f"Restored Qt Designer plugin: {designer.name}")

    if onefile:
        artifact = ROOT / "dist" / (NAME + (".exe" if system == "Windows" else ""))
        if versioned:
            artifact = _rename_versioned(artifact, version)
    else:
        artifact = ROOT / "dist" / NAME

    _verify_artifact(artifact)

    print(f"\nBuild complete: {artifact}")
    if not onefile:
        print("Distribution folder:", ROOT / "dist")
    return artifact


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