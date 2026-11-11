"""Offscreen regression test for the native-library bootstrap and diagnostics.

Covers the three things that turned "the app does not start on Windows" into
an undebuggable mystery:

* the native library is located and exported via ``HTTPCLOAK_LIB_PATH``;
* a missing native library produces an actionable error, not a bare OSError;
* an unhandled exception — including one on a worker thread — lands in
  ``error.log`` instead of vanishing.

It also exercises ``tools/verify_bundle.py``, the CI gate that refuses to
publish a bundle whose native library is missing.

Usage::

    QT_QPA_PLATFORM=offscreen python src/tests/test_native_lib.py

Exit code is 0 on success, non-zero on failure.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import traceback
from pathlib import Path

# Make repo-root imports work no matter where this is run from.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.core.diagnostics as diagnostics
import src.core.native_lib as native_lib
from src.core.native_lib import NativeLibError, native_lib_name


def _load_verifier():
    """Import tools/verify_bundle.py (not a package) by path."""
    path = ROOT / "tools" / "verify_bundle.py"
    spec = importlib.util.spec_from_file_location("verify_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_lib_name_per_platform():
    """The library name must match what httpcloak looks for."""
    assert native_lib_name("Windows", "AMD64") == "libhttpcloak-windows-amd64.dll"
    assert native_lib_name("windows", "x86_64") == "libhttpcloak-windows-amd64.dll"
    assert native_lib_name("Darwin", "arm64") == "libhttpcloak-darwin-arm64.dylib"
    assert native_lib_name("Linux", "x86_64") == "libhttpcloak-linux-amd64.so"
    assert native_lib_name("Linux", "aarch64") == "libhttpcloak-linux-arm64.so"


def test_find_native_lib_locates_the_installed_library():
    """The installed httpcloak package must be discoverable."""
    found = native_lib.find_native_lib()
    if found is None:
        print("      (skipped: httpcloak is not installed)")
        return
    assert found.is_file(), f"found a path that is not a file: {found}"
    assert found.name == native_lib_name(), (
        f"found {found.name}, expected {native_lib_name()}"
    )


def test_ensure_native_lib_exports_the_path():
    """HTTPCLOAK_LIB_PATH must point at the resolved library."""
    previous = os.environ.get("HTTPCLOAK_LIB_PATH")
    try:
        path = native_lib.ensure_native_lib()
        assert path.is_file()
        assert os.environ["HTTPCLOAK_LIB_PATH"] == str(path)
    finally:
        if previous is None:
            os.environ.pop("HTTPCLOAK_LIB_PATH", None)
        else:
            os.environ["HTTPCLOAK_LIB_PATH"] = previous


def test_ensure_native_lib_reports_a_missing_library(tmp_path):
    """A missing library must raise an actionable error, not a bare OSError."""
    original_dirs = native_lib._candidate_dirs
    native_lib._candidate_dirs = lambda: [tmp_path]
    try:
        try:
            native_lib.ensure_native_lib()
        except NativeLibError as exc:
            message = str(exc)
            assert "not found" in message
            assert "error.log" in message, "error message must point at the log"
        else:
            raise AssertionError("expected NativeLibError")
    finally:
        native_lib._candidate_dirs = original_dirs


def test_error_log_records_a_traceback(tmp_path):
    """An unhandled exception must be written to error.log with its traceback."""
    original_error_file = diagnostics.ERROR_FILE
    diagnostics.ERROR_FILE = tmp_path / "error.log"
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            diagnostics._append_error_log(*sys.exc_info())
        text = diagnostics.ERROR_FILE.read_text(encoding="utf-8")
        assert "ValueError: boom" in text
        assert "Traceback" in text
    finally:
        diagnostics.ERROR_FILE = original_error_file


def test_thread_exceptions_are_captured(tmp_path):
    """A crash on a worker thread must not vanish silently."""
    original_error_file = diagnostics.ERROR_FILE
    original_show = diagnostics._show_critical
    diagnostics.ERROR_FILE = tmp_path / "error.log"
    original_hook = sys.excepthook
    try:
        # Swallow the error dialog — this test is about the log file.
        diagnostics._show_critical = lambda title, text: None
        diagnostics.install_excepthooks()

        def _boom():
            raise RuntimeError("worker exploded")

        thread = threading.Thread(target=_boom)
        thread.start()
        thread.join()

        text = diagnostics.ERROR_FILE.read_text(encoding="utf-8")
        assert "RuntimeError: worker exploded" in text
    finally:
        sys.excepthook = original_hook
        diagnostics._show_critical = original_show
        diagnostics.ERROR_FILE = original_error_file


def test_verify_bundle_flags_a_missing_library(tmp_path):
    """The CI verifier must fail a bundle that has no native library."""
    verifier = _load_verifier()
    bundle = tmp_path / "NaukriProfileManager"
    (bundle / "httpcloak" / "lib").mkdir(parents=True)
    assert verifier.verify(bundle, "linux", "x86_64") == 1, (
        "a bundle without the native library must be rejected"
    )


def test_verify_bundle_accepts_a_complete_bundle(tmp_path):
    """The CI verifier must accept a bundle that carries the native library."""
    verifier = _load_verifier()
    source = native_lib.find_native_lib()
    if source is None:
        print("      (skipped: httpcloak is not installed)")
        return

    bundle = tmp_path / "NaukriProfileManager-complete"
    lib_dir = bundle / "httpcloak" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    # Copy every DLL/SO from httpcloak's lib dir (native lib + companion DLLs)
    # so the dependency-closure check passes on Windows too.
    for sibling in source.parent.glob("*"):
        if sibling.is_file():
            shutil.copy2(sibling, lib_dir / sibling.name)

    assert verifier.verify(bundle, "linux", "x86_64") == 0


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="naukri_native_lib_test_"))
    tests = [
        ("test_native_lib_name_per_platform", test_native_lib_name_per_platform),
        ("test_find_native_lib_locates_the_installed_library",
         test_find_native_lib_locates_the_installed_library),
        ("test_ensure_native_lib_exports_the_path",
         test_ensure_native_lib_exports_the_path),
        ("test_ensure_native_lib_reports_a_missing_library",
         lambda: test_ensure_native_lib_reports_a_missing_library(tmp)),
        ("test_error_log_records_a_traceback",
         lambda: test_error_log_records_a_traceback(tmp)),
        ("test_thread_exceptions_are_captured",
         lambda: test_thread_exceptions_are_captured(tmp)),
        ("test_verify_bundle_flags_a_missing_library",
         lambda: test_verify_bundle_flags_a_missing_library(tmp)),
        ("test_verify_bundle_accepts_a_complete_bundle",
         lambda: test_verify_bundle_accepts_a_complete_bundle(tmp)),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            failures += 1
            print(f"FAIL {name}: {exc}")
            traceback.print_exc()

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nAll native library tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
