"""Cookie helpers that work with httpcloak's cookie list and a standard
requests CookieJar alike. The vendored NopeRi was written for `requests`,
whose `session.cookies` is a `RequestsCookieJar` (dict-like). The default
httpcloak backend stores cookies as a plain `list` of `Cookie` objects, so
we normalise access through these helpers.
"""


def get_cookie(session, name: str) -> str | None:
    """Return the value of the named cookie, or None if absent."""
    cookies = getattr(session, "cookies", [])
    if isinstance(cookies, list):
        for c in cookies:
            if c.name == name:
                return c.value
        return None
    # requests CookieJar path
    return cookies.get(name)


def cookies_to_dict(session) -> dict:
    """Return all cookies as a {name: value} dict."""
    cookies = getattr(session, "cookies", [])
    if isinstance(cookies, list):
        return {c.name: c.value for c in cookies}
    if isinstance(cookies, dict):
        return dict(cookies)
    return dict(cookies.get_dict())


def set_cookies(session, cookies: dict) -> None:
    """Re-inject persisted {name: value} cookies into the session.

    httpcloak exposes a native `set_cookie(...)` that persists into the C
    session handle; it is the only path that survives. The `.cookies`
    attribute is a copy-on-read view, so appending to it is a silent no-op.
    For the requests CookieJar backend we call `.update()`.
    """
    setter = getattr(session, "set_cookie", None)
    if setter is not None:
        for name, value in cookies.items():
            setter(name, value, domain=".naukri.com", path="/",
                   secure=True, same_site="Lax")
        return
    jar = getattr(session, "cookies", [])
    if not isinstance(jar, list):
        jar.update(cookies)