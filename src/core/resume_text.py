from io import BytesIO

from pypdf import PdfReader

from src.core.naukri_client import NaukriManager


class ResumeTextError(Exception):
    """Raised when resume content cannot be obtained or extracted."""


def extract_resume_text(manager: NaukriManager) -> str:
    """Download the on-file Naukri resume and return its full extracted text.

    Only text-based PDFs are supported. Non-PDF formats and PDFs with no
    extractable text (e.g. scanned/image-based) raise ``ResumeTextError``.
    """
    profile = manager.fetch_profile()
    if not profile.resume_available and not profile.resume_format:
        raise ResumeTextError("No resume is currently on-file on Naukri.")
    fmt = (profile.resume_format or "").lower()
    if fmt != "pdf":
        raise ResumeTextError(
            f"The on-file resume is a .{fmt}; only PDF resumes are supported "
            "for AI content extraction. Paste the text manually instead."
        )

    content = manager.download_resume()
    if not content:
        raise ResumeTextError("The on-file resume downloaded no data.")

    reader = PdfReader(BytesIO(content))
    chunks = []
    for page in reader.pages:
        try:
            text = page.extract_text()
        except Exception as exc:  # pragma: no cover - pypdf edge cases
            raise ResumeTextError(f"Could not read a resume page: {exc}") from exc
        if text and text.strip():
            chunks.append(text.strip())

    result = "\n".join(chunks).strip()
    if not result:
        raise ResumeTextError(
            "The resume PDF contains no extractable text "
            "(it may be a scanned/image PDF). Paste the text manually instead."
        )
    return result