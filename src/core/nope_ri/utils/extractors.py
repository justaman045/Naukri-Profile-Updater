import re

from ..config.constants import RESUME_FORM_KEY_PATTERNS

# Older bundles exposed the upload key as `key:"initUploader" ... d="<key>"`.
# Keep them as a last resort in case Naukri rolls the signature back.
_LEGACY_FORM_KEY_PATTERNS = (
    re.compile(r'key:"initUploader".*?d\s*=\s*"([A-Za-z0-9]+)"', re.DOTALL),
    re.compile(r'd\s*=\s*"([A-Za-z0-9]{10,})"'),
)


def extract_resume_form_key(js_text: str) -> str | None:
    """Extract the profile resume uploader's formKey (`c="attachCV",d="<key>"`)."""
    for pattern in RESUME_FORM_KEY_PATTERNS:
        match = pattern.search(js_text)
        if match:
            return match.group(1)
    return None


def extract_form_key2(js_text: str) -> str | None:
    """Best-effort resume formKey from an arbitrary bundle.

    Deliberately does NOT consider the app-shell `formKey="..."` shape: that is
    the chat uploader's key from `app_v<NNN>.min.js`, and submitting it makes
    filevalidation return a honeypot key that `advResume` cannot resolve
    (404 "Received 404 from OCS Service"). Returning None and failing loudly
    beats returning a key that looks valid and silently breaks the upload.
    """
    for pattern in (*RESUME_FORM_KEY_PATTERNS, *_LEGACY_FORM_KEY_PATTERNS):
        match = pattern.search(js_text)
        if match:
            return match.group(1)
    return None

def extract_all_js_urls(html: str):
    return re.findall(r'<script[^>]+src="([^"]*\.js[^"]*)"', html)
