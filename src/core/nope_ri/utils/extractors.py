import re

from ..config.constants import FORM_KEY_PATTERNS, RESUME_FORM_KEY_PATTERNS

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
    for pattern in (*RESUME_FORM_KEY_PATTERNS, *FORM_KEY_PATTERNS, *_LEGACY_FORM_KEY_PATTERNS):
        match = pattern.search(js_text)
        if match:
            return match.group(1)
    return None

def extract_all_js_urls(html: str):
    return re.findall(r'<script[^>]+src="([^"]*\.js[^"]*)"', html)
