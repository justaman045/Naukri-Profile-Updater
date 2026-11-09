#!/usr/bin/env python3
"""Verify that a built bundle actually contains httpcloak's native library.

Usage::

    python tools/verify_bundle.py dist/NaukriProfileManager-0.6.0-windows-x86_64.exe
    python tools/verify_bundle.py dist/NaukriProfileManager

Checks:

1. httpcloak's native library is present in the bundle;
2. every non-system library it depends on is present too.

Check 2 is the one that matters. On Windows the httpcloak DLL is built with
MinGW and needs ``libgcc_s_seh-1.dll`` plus a few OpenSSL DLLs. A bundle that
is missing those still builds and still loads fine on the build machine —
where those DLLs happen to be installed — and then fails on every user's
machine with ``OSError: [WinError 126] The specified module could not be
found``. Verifying the whole dependency closure turns that silent,
user-facing breakage into a failed CI job.

Exit code is 0 when the bundle is good, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

# DLLs that Windows itself provides. Anything a PE file imports that is not
# in this list and not in the bundle is a packaging bug.
WINDOWS_SYSTEM_DLLS = {
    "advapi32.dll", "bcrypt.dll", "cabinet.dll", "combase.dll", "comctl32.dll",
    "comdlg32.dll", "crypt32.dll", "cryptbase.dll", "cryptsp.dll", "d3d9.dll",
    "d3d11.dll", "d3d12.dll", "d3dcompiler_47.dll", "dcrypt.dll", "dnsapi.dll",
    "dsound.dll", "dwmapi.dll", "dxgi.dll", "gdi32.dll", "gdi32full.dll",
    "imagehlp.dll", "imm32.dll", "iphlpapi.dll", "kernel32.dll", "mpr.dll",
    "msacm32.dll", "msasn1.dll", "mscoree.dll", "msi.dll", "msimg32.dll",
    "msvcrt.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "netapi32.dll", "normaliz.dll", "nsi.dll", "ntmarta.dll", "ole32.dll",
    "oleaut32.dll", "opengl32.dll", "powrprof.dll", "propsys.dll",
    "psapi.dll", "rpcrt4.dll", "secur32.dll", "setupapi.dll", "shell32.dll",
    "shlwapi.dll", "sspicli.dll", "ucrtbase.dll", "user32.dll", "userenv.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "winhttp.dll", "wininet.dll",
    "winmm.dll", "winspool.drv", "wintrust.dll", "wldap32.dll", "ws2_32.dll",
    "ws2help.dll", "wtsapi32.dll",
}

# Shared libraries that every glibc Linux provides. Anything else the native
# library needs has to travel with the bundle.
LINUX_CORE_LIBS = {
    "ld-linux-x86-64.so.2", "ld-linux-aarch64.so.1", "ld-linux-armhf.so.3",
    "linux-vdso.so.1", "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0",
    "librt.so.1", "libresolv.so.2", "libutil.so.1", "libcrypt.so.1",
    "libgcc_s.so.1", "libnsl.so.1", "libanl.so.1",
}


def native_lib_name(system: str | None = None, machine: str | None = None) -> str:
    """The file name httpcloak uses for the given platform."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine
    if system == "darwin":
        ext, os_name = ".dylib", "darwin"
    elif system == "windows":
        ext, os_name = ".dll", "windows"
    else:
        ext, os_name = ".so", "linux"
    return f"libhttpcloak-{os_name}-{arch}{ext}"


class Bundle:
    """Read-only view of a built artifact (onefile archive or onedir folder).

    Archive member names are normalised to forward slashes: PyInstaller stores
    them with the separator of the *build* machine, so a Windows bundle read
    on Linux has entries like ``httpcloak\\lib\\libhttpcloak-windows-amd64.dll``.
    """

    def __init__(self, path: Path):
        self.path = path
        self._reader = None
        self._root: Path | None = None
        self._names: dict[str, str] = {}
        if path.is_dir():
            self._root = path
            for dirpath, _dirs, files in os.walk(self._root):
                for name in files:
                    full = Path(dirpath) / name
                    rel = full.relative_to(self._root).as_posix()
                    self._names[rel] = rel
        else:
            try:
                from PyInstaller.archive.readers import CArchiveReader
            except ImportError as exc:
                raise SystemExit(
                    "PyInstaller is required to inspect a onefile bundle. "
                    "Install it with: pip install pyinstaller"
                ) from exc

            self._reader = CArchiveReader(str(path))
            for name in self._reader.toc:
                self._names[name.replace("\\", "/")] = name

    def names(self) -> set[str]:
        """Archive-relative names of every file in the bundle."""
        return set(self._names.keys())

    def basenames(self) -> set[str]:
        """Lower-cased file names, ignoring directories."""
        return {PurePosixPath(n).name.lower() for n in self._names}

    def read(self, name: str) -> bytes:
        """Raw bytes of one archive member."""
        if self._root is not None:
            return (self._root / name).read_bytes()
        return self._reader.extract(self._names[name])

    def find(self, predicate) -> str | None:
        """First archive-relative name satisfying ``predicate``."""
        for name in sorted(self._names.keys()):
            if predicate(name):
                return name
        return None


def _is_api_set(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("api-ms-win-") or lowered.startswith("ext-ms-")


def check_windows_dependencies(bundle: Bundle, member: str) -> list[str]:
    """Return the DLLs the native library needs that the bundle is missing."""
    try:
        import pefile
    except ImportError:
        print("  ! pefile is not installed — skipping the dependency check")
        return []

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / Path(member).name
        target.write_bytes(bundle.read(member))
        pe = pefile.PE(str(target), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        imported = {
            entry.dll.decode().lower()
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
        }
        pe.close()

    present = bundle.basenames()
    missing = []
    for dll in sorted(imported):
        if _is_api_set(dll) or dll in WINDOWS_SYSTEM_DLLS:
            continue
        if dll not in present:
            missing.append(dll)
    return missing


def check_posix_dependencies(bundle: Bundle, member: str, system: str) -> list[str]:
    """Return the shared libraries the native library needs but cannot find."""
    missing: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / Path(member).name
        target.write_bytes(bundle.read(member))

        if system == "darwin":
            try:
                out = subprocess.run(
                    ["otool", "-L", str(target)],
                    capture_output=True, text=True, check=True,
                ).stdout
            except (OSError, subprocess.CalledProcessError):
                print("  ! otool unavailable — skipping the dependency check")
                return []
            present = bundle.basenames()
            for line in out.splitlines()[1:]:
                dep = line.strip().split(" ")[0]
                if not dep:
                    continue
                if dep.startswith(("@rpath/", "@loader_path/", "@executable_path/")):
                    if Path(dep).name.lower() not in present:
                        missing.append(dep)
                elif dep.startswith("/usr/lib/") or dep.startswith("/System/"):
                    # Shipped with macOS itself.
                    continue
                elif Path(dep).name.lower() not in present:
                    missing.append(dep)
            return missing

        # Linux: anything outside the core glibc set has to travel with the
        # bundle — the user's machine may not have the same OpenSSL.
        try:
            target.chmod(0o755)
            out = subprocess.run(
                ["ldd", str(target)], capture_output=True, text=True, check=False
            ).stdout
        except OSError:
            print("  ! ldd unavailable — skipping the dependency check")
            return []

        present = bundle.basenames()
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if "=>" in line:
                soname = line.split("=>")[0].strip()
            else:
                # "/lib64/ld-linux-x86-64.so.2 (0x...)" or "linux-vdso.so.1 (...)"
                soname = line.split(" ")[0]
            # ldd prints the loader as a full path, everything else as a soname.
            base = PurePosixPath(soname).name
            if base in LINUX_CORE_LIBS:
                continue
            if base.lower() not in present:
                missing.append(soname)
    return missing


def verify(path: Path, system: str | None = None, machine: str | None = None) -> int:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    wanted = native_lib_name(system, machine)
    print(f"Verifying bundle: {path}")
    print(f"  platform: {system} / {machine} -> expecting {wanted}")

    if not path.exists():
        print(f"  ! bundle does not exist: {path}")
        return 1

    bundle = Bundle(path)
    names = bundle.names()

    member = bundle.find(
        lambda n: PurePosixPath(n).name.lower() == wanted.lower()
        and "httpcloak" in n.lower()
    )
    if member is None:
        member = bundle.find(
            lambda n: PurePosixPath(n).name.lower().startswith("libhttpcloak")
        )
    if member is None:
        print(f"  ! {wanted} is NOT in the bundle")
        print("    the app would fail at start-up with 'Could not find "
              "httpcloak library'")
        return 1

    print(f"  found native library: {member}")

    if system == "windows":
        missing = check_windows_dependencies(bundle, member)
    else:
        missing = check_posix_dependencies(bundle, member, system)

    if missing:
        print("  ! the native library depends on files that are NOT in the "
              "bundle:")
        for name in missing:
            print(f"      {name}")
        print("    the app would fail on a clean machine with "
              "'The specified module could not be found'")
        return 1

    print(f"  dependency closure OK ({len(names)} files in bundle)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="built artifact (onefile .exe or onedir folder)")
    parser.add_argument(
        "--system",
        default=None,
        help="override the target OS (linux/darwin/windows); defaults to this machine",
    )
    parser.add_argument(
        "--machine",
        default=None,
        help="override the target arch (x86_64/arm64); defaults to this machine",
    )
    args = parser.parse_args()
    return verify(Path(args.path).resolve(), args.system, args.machine)


if __name__ == "__main__":
    raise SystemExit(main())
