"""Locate, prepare and load httpcloak's native shared library.

httpcloak ships a platform-specific native library (``libhttpcloak-<os>-<arch>``
plus a ``.so``/``.dll``/``.dylib`` extension) in a ``lib`` directory next to
its Python package, and loads it lazily with ``ctypes.cdll.LoadLibrary`` the
first time a :class:`httpcloak.Session` is constructed.

Two things make that fragile inside a frozen (PyInstaller) build:

* **The library is not collected automatically.** PyInstaller ships no hook
  for httpcloak, so ``build.py`` bundles it by hand into ``httpcloak/lib/`` —
  the exact directory httpcloak searches (``Path(__file__).parent / "lib"``).
* **A missing *dependency* looks like a missing library.** On Windows the
  httpcloak DLL is built with MinGW and needs ``libgcc_s_seh-1.dll`` plus a
  few OpenSSL DLLs that ship beside it. If any of those cannot be resolved,
  Windows raises ``OSError: [WinError 126] The specified module could not be
  found`` — a message that never names the DLL that is actually missing.

This module removes both failure modes:

* it resolves the library explicitly (bundle root first, installed package
  second) instead of relying on ``__file__`` guessing;
* on Windows it registers the library's own directory *and* the bundle root
  with :func:`os.add_dll_directory`, so sibling dependencies resolve; and
* it exports ``HTTPCLOAK_LIB_PATH``, which httpcloak honours ahead of its own
  search, so the two implementations can never disagree.

:func:`ensure_native_lib` is called once at start-up. It raises
:class:`NativeLibError` with an actionable message instead of letting a bare
``OSError`` kill the GUI process.
"""

import ctypes
import logging
import os
import platform
import sys
from pathlib import Path

from src.core.diagnostics import error_log_path

logger = logging.getLogger(__name__)

__all__ = [
    "NativeLibError",
    "bootstrap_native_lib",
    "ensure_native_lib",
    "find_native_lib",
    "native_lib_name",
]


class NativeLibError(RuntimeError):
    """Raised when httpcloak's native library cannot be found or loaded."""


# Handles returned by os.add_dll_directory(). They must stay alive for the
# lifetime of the process: dropping one removes that directory from the DLL
# search path again.
_DLL_DIR_HANDLES: list[object] = []

_bootstrapped = False


def _arch(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


def native_lib_name(system: str | None = None, machine: str | None = None) -> str:
    """Return the file name httpcloak uses for the given platform."""
    system = (system or platform.system()).lower()
    if system == "darwin":
        ext, os_name = ".dylib", "darwin"
    elif system == "windows":
        ext, os_name = ".dll", "windows"
    else:
        ext, os_name = ".so", "linux"
    return f"libhttpcloak-{os_name}-{_arch(machine)}{ext}"


def _candidate_dirs() -> list[Path]:
    """Directories that may hold the native library, most likely first."""
    dirs: list[Path] = []

    # Frozen build: build.py bundles the library at httpcloak/lib/<name>.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        dirs.append(root / "httpcloak" / "lib")
        dirs.append(root / "lib")
        dirs.append(root)

    # Source checkout / pip install: next to the httpcloak package.
    try:
        import httpcloak
    except Exception:  # noqa: BLE001 - httpcloak may not be installed at all
        pass
    else:
        pkg = Path(httpcloak.__file__).resolve().parent
        dirs.append(pkg / "lib")
        dirs.append(pkg)
        dirs.append(pkg.parent / "lib")

    seen: set[str] = set()
    unique: list[Path] = []
    for directory in dirs:
        key = str(directory)
        if key not in seen:
            seen.add(key)
            unique.append(directory)
    return unique


def find_native_lib() -> Path | None:
    """Locate the native library, or return None when it is not present."""
    wanted = native_lib_name()
    stem, ext = os.path.splitext(wanted)
    fallback: Path | None = None

    for directory in _candidate_dirs():
        if not directory.is_dir():
            continue
        exact = directory / wanted
        if exact.is_file():
            return exact
        # Tolerate upstream renames or version suffixes.
        for pattern in (f"{stem}*{ext}", f"libhttpcloak*{ext}"):
            for candidate in sorted(directory.glob(pattern)):
                if candidate.is_file() and fallback is None:
                    fallback = candidate

    return fallback


def bootstrap_native_lib() -> Path | None:
    """Prepare the process so httpcloak can load its native library.

    Registers the library's directory (and, in a frozen build, the bundle
    root) with the OS DLL search path, points ``HTTPCLOAK_LIB_PATH`` at the
    resolved file, and returns the path. Returns None when the library is not
    present at all.
    """
    global _bootstrapped
    if _bootstrapped:
        return find_native_lib()

    path = find_native_lib()
    if path is None:
        logger.error("httpcloak native library %s not found", native_lib_name())
        return None

    if sys.platform == "win32":
        directories = [path.parent]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            directories.append(Path(meipass))
        for directory in directories:
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(str(directory)))
            except (OSError, AttributeError):
                # add_dll_directory is unavailable on exotic setups; the
                # explicit HTTPCLOAK_LIB_PATH below still gives httpcloak the
                # file itself, and PyInstaller's bootloader already puts the
                # bundle root on the DLL search path.
                pass

    os.environ["HTTPCLOAK_LIB_PATH"] = str(path)
    _bootstrapped = True
    logger.info("httpcloak native library: %s", path)
    return path


def ensure_native_lib() -> Path:
    """Make sure httpcloak's native library is present and loadable.

    Raises :class:`NativeLibError` with an actionable message when it is not.
    """
    path = bootstrap_native_lib()
    if path is None:
        searched = ", ".join(str(d) for d in _candidate_dirs())
        raise NativeLibError(
            f"httpcloak's native library ({native_lib_name()}) was not found. "
            f"Searched: {searched}. This is a packaging problem — please "
            f"report it and attach {error_log_path()}."
        )

    try:
        # Load it here so a broken dependency surfaces as a readable error
        # instead of an OSError from deep inside httpcloak's session setup.
        # httpcloak loads the same file again later; Windows returns the
        # already-loaded module, so this costs nothing.
        ctypes.cdll.LoadLibrary(str(path))
    except OSError as exc:
        logger.error("httpcloak native library %s failed to load: %s", path, exc)
        raise NativeLibError(
            f"httpcloak's native library ({path}) could not be loaded: {exc}. "
            "A dependency of that library is probably missing. Please report "
            f"it and attach {error_log_path()}."
        ) from exc

    logger.info("httpcloak native library loaded OK")
    return path
