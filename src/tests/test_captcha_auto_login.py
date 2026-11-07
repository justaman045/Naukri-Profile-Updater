"""Offscreen regression test for the captcha auto-login flow.

Runs headless (no display). Spawns no real browser — instead it stubs
``login_via_browser.py`` with a temporary script that writes a fake
``session.json`` so the dialog can adopt the session it ``produces``.

Usage::

    QT_QPA_PLATFORM=offscreen python src/tests/test_captcha_auto_login.py

Exit code is 0 on success, non-zero on failure.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog

# Make repo-root imports work no matter where this is run from.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.core.session_store as session_store
import src.ui.login_dialog as ld
from src.core import credentials as cred_mod
from src.core.naukri_client import NaukriCaptchaError
from src.core.nope_ri.exceptions.exceptions import NaukriAuthError

ORIG_ROOT = ld.ROOT
ORIG_SESSION_FILE = session_store.SESSION_FILE
ORIG_CREDENTIALS_FILE = cred_mod.CREDENTIALS_FILE


def _spin_until_done(dlg: ld.LoginDialog, ms: int = 20000) -> None:
    """Spin the Qt event loop until the browser helper process exits."""
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: dlg._browser_proc is None and loop.quit())
    poll.start(50)
    hard = QTimer()
    hard.setSingleShot(True)
    hard.timeout.connect(loop.quit)
    hard.start(ms)
    loop.exec()


def _restore():
    ld.ROOT = ORIG_ROOT
    session_store.SESSION_FILE = ORIG_SESSION_FILE
    cred_mod.CREDENTIALS_FILE = ORIG_CREDENTIALS_FILE


def test_naukri_captcha_error_is_auth_error():
    """NaukriCaptchaError must remain a NaukriAuthError so auth handling applies."""
    assert issubclass(NaukriCaptchaError, NaukriAuthError)
    err = NaukriCaptchaError("boom")
    assert isinstance(err, NaukriAuthError)
    assert "[AUTH ERROR]" in str(err)


def test_captcha_preserves_stored_password(tmp_path):
    """ensure_credential must not clobber an existing stored password."""
    cred_mod.CREDENTIALS_FILE = tmp_path / "credentials.json"
    try:
        cred_mod.save_credential("a@b.c", "secret", True)
        cred_mod.ensure_credential("a@b.c")
        assert cred_mod.get_credential("a@b.c").password == "secret", "stored password clobbered"
        assert cred_mod.get_credential("a@b.c").remember_password is True
        cred_mod.ensure_credential("new@b.c")
        assert cred_mod.get_credential("new@b.c").password == ""
        assert cred_mod.get_credential("new@b.c").remember_password is False
    finally:
        cred_mod.CREDENTIALS_FILE = ORIG_CREDENTIALS_FILE


def test_captcha_auto_login_adopts_session(tmp_path):
    """When the helper writes a valid session, LoginDialog accepts with a manager."""
    sess = tmp_path / "session.json"
    stub = tmp_path / "login_via_browser.py"
    stub.write_text(
        "import json, sys\n"
        f"open({str(sess)!r}, 'w').write(json.dumps({{'username': 'x@y.z', 'bearer_token': 'tok', 'cookies': {{}}}}))\n"
        "sys.exit(0)\n"
    )

    ld.ROOT = tmp_path
    session_store.SESSION_FILE = sess
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = ld.LoginDialog()
        dlg.email.setText("x@y.z")
        dlg.show()
        app.processEvents()
        dlg._on_login_failure(NaukriCaptchaError("Naukri requires a captcha"))
        _spin_until_done(dlg)
        assert dlg.result() == QDialog.DialogCode.Accepted
        assert dlg.manager is not None
        assert dlg.manager.has_saved_session
    finally:
        _restore()


def test_captcha_broken_helper_shows_error(tmp_path):
    """When the helper crashes, the dialog shows an error instead of hanging."""
    stub = tmp_path / "login_via_browser.py"
    stub.write_text("import sys; sys.exit(3)\n")

    ld.ROOT = tmp_path
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = ld.LoginDialog()
        dlg.show()
        app.processEvents()
        dlg._on_login_failure(NaukriCaptchaError("Naukri requires a captcha"))
        _spin_until_done(dlg)
        assert dlg.result() != QDialog.DialogCode.Accepted
        assert dlg.error_label.isVisible()
        assert "Browser login failed" in dlg.error_label.text()
    finally:
        _restore()


def test_captcha_missing_helper_shows_error(tmp_path):
    """When login_via_browser.py does not exist, the dialog shows an error."""
    ld.ROOT = tmp_path
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = ld.LoginDialog()
        dlg.show()
        app.processEvents()
        dlg._on_login_failure(NaukriCaptchaError("Naukri requires a captcha"))
        # Flush any pending layout/visibility events before asserting.
        app.processEvents()
        app.processEvents()
        assert dlg.result() != QDialog.DialogCode.Accepted
        # The error text is set unconditionally in _show_error before setVisible,
        # so it is the more reliable signal than isVisible() under offscreen Qt.
        assert "was not found" in dlg.error_label.text()
    finally:
        _restore()


def test_parse_session_token_bare():
    """A bare JWT token is parsed as bearer_token with nauk_at cookie."""
    token, cookies = ld.LoginDialog._parse_session_token(ld.LoginDialog, "eyJhbGciOiJIUzI1NiJ9")
    assert token == "eyJhbGciOiJIUzI1NiJ9"
    assert cookies == {"nauk_at": "eyJhbGciOiJIUzI1NiJ9"}


def test_parse_session_token_cookie_fragment():
    """nauk_at=eyJ... is parsed correctly."""
    token, cookies = ld.LoginDialog._parse_session_token(ld.LoginDialog, "nauk_at=eyJhbGciOiJIUzI1NiJ9")
    assert token == "eyJhbGciOiJIUzI1NiJ9"
    assert cookies == {"nauk_at": "eyJhbGciOiJIUzI1NiJ9"}


def test_parse_session_token_cookie_header():
    """Raw Cookie header with nauk_at among other cookies."""
    token, cookies = ld.LoginDialog._parse_session_token(
        ld.LoginDialog, "nauk_at=eyJhbGciOiJIUzI1NiJ9; _ga=GA1.2.abc; theme=dark"
    )
    assert token == "eyJhbGciOiJIUzI1NiJ9"
    assert cookies == {"nauk_at": "eyJhbGciOiJIUzI1NiJ9"}


def test_parse_session_token_bearer():
    """Bearer eyJ... prefix is stripped."""
    token, cookies = ld.LoginDialog._parse_session_token(
        ld.LoginDialog, "Bearer eyJhbGciOiJIUzI1NiJ9"
    )
    assert token == "eyJhbGciOiJIUzI1NiJ9"
    assert cookies == {"nauk_at": "eyJhbGciOiJIUzI1NiJ9"}


def test_parse_session_token_empty():
    """Empty input yields empty token and no cookies."""
    token, cookies = ld.LoginDialog._parse_session_token(ld.LoginDialog, "")
    assert token == ""
    assert cookies == {}


def test_apply_session_accepts_dialog(tmp_path):
    """Pasting a valid session token saves the session and accepts the dialog."""
    sess = tmp_path / "session.json"
    ld.ROOT = tmp_path
    session_store.SESSION_FILE = sess
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = ld.LoginDialog()
        dlg.email.setText("user@example.com")
        dlg.show()
        app.processEvents()

        # Simulate the frozen-build flow: show session input, paste token, apply.
        dlg.session_input.setText("eyJhbGciOiJIUzI1NiJ9")
        dlg._on_apply_session()

        assert dlg.result() == QDialog.DialogCode.Accepted
        assert dlg.manager is not None
        assert dlg.manager.has_saved_session

        # Verify session.json was written.
        import json
        saved = json.loads(sess.read_text(encoding="utf-8"))
        assert saved["bearer_token"] == "eyJhbGciOiJIUzI1NiJ9"
        assert saved["cookies"] == {"nauk_at": "eyJhbGciOiJIUzI1NiJ9"}
    finally:
        _restore()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="naukri_captcha_test_"))

    tests = [
        ("test_naukri_captcha_error_is_auth_error", test_naukri_captcha_error_is_auth_error),
        ("test_captcha_preserves_stored_password", lambda: test_captcha_preserves_stored_password(tmp)),
        # Run missing-helper before any QProcess-spawning test, because a prior
        # QProcess/deleteLater can leave Qt in a state where a freshly created
        # dialog doesn't process its error label correctly.
        ("test_captcha_missing_helper_shows_error", lambda: test_captcha_missing_helper_shows_error(tmp)),
        ("test_parse_session_token_bare", test_parse_session_token_bare),
        ("test_parse_session_token_cookie_fragment", test_parse_session_token_cookie_fragment),
        ("test_parse_session_token_cookie_header", test_parse_session_token_cookie_header),
        ("test_parse_session_token_bearer", test_parse_session_token_bearer),
        ("test_parse_session_token_empty", test_parse_session_token_empty),
        ("test_captcha_auto_login_adopts_session", lambda: test_captcha_auto_login_adopts_session(tmp)),
        ("test_apply_session_accepts_dialog", lambda: test_apply_session_accepts_dialog(tmp)),
        ("test_captcha_broken_helper_shows_error", lambda: test_captcha_broken_helper_shows_error(tmp)),
    ]

    failures = []
    app = QApplication.instance() or QApplication(sys.argv)
    for name, fn in tests:
        try:
            fn()
            # Flush pending Qt events (QProcess deleteLater, dialog close, etc.)
            # between tests so they don't leak into each other.
            for _ in range(3):
                app.processEvents()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            failures.append((name, exc))
            import traceback
            print(f"FAIL {name}: {type(exc).__name__}: {exc!r}")
            traceback.print_exc()

    shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print("\nAll captcha auto-login tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
