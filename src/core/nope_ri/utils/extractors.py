import re

from ..config.constants import RESUME_FORM_KEY_PATTERNS

# Older bundles exposed the upload key as `key:"initUploader" ... d="<key>"`.
# Keep them as a last resort in case Naukri rolls the signature back.
_LEGACY_FORM_KEY_PATTERNS = (
    re.compile(r'key:"initUploader".*?d\s*=\s*"([A-Za-z0-9]+)"', re.DOTALL),
    re.compile(r'd\s*=\s*"([A-Za-z0-9]{10,})"'),
)


def extract_resume_form_key(js_text: str) -> str | None:
    """Extract the profile resume uploader's formKey.

    The resume uploader's config object carries `formKey:"<key>"` with
    extensions including "pdf" (current SPA bundle), or the legacy
    `c="attachCV",d="<key>"` shape.
    """
    for pattern in RESUME_FORM_KEY_PATTERNS:
        match = pattern.search(js_text)
        if match:
            return match.group(1)
    return None


def extract_form_key2(js_text: str) -> str | None:
    """Best-effort resume formKey from an arbitrary bundle.

    Only the resume-uploader shapes are considered. The legacy
    ``d="..."`` / ``initUploader`` patterns are intentionally excluded: they
    match Naukri's honeypot key (``0123456789ABCDEF``) which makes
    filevalidation succeed but advResume fail with 404 "OCS Service".
    """
    for pattern in RESUME_FORM_KEY_PATTERNS:
        match = pattern.search(js_text)
        if match:
            return match.group(1)
    return None

def extract_all_js_urls(html: str):
    return re.findall(r'<script[^>]+src="([^"]*\.js[^"]*)"', html)
