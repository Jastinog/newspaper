"""Build a clean classification premise from an article's title + content.

Extracted article bodies often start with noise that misdirects the classifier:
photo captions, agency credits ("… / Courtesy of X", "… Yonhap"), and datelines
("CHARLOTTESVILLE, VIRGINIA — …", "SEOUL (Reuters) - …"). Feeding that lead to
the model tanks the scores (e.g. a KOSPI story scored business 0.01 with the raw
"dealing room … Yonhap" caption, 0.92 on the real sentence). This strips the
boilerplate and returns the first substantive prose.
"""

import re

_AGENCIES = (
    r"Yonhap|Reuters|AP|AFP|AP Photo|Getty(?: Images)?|EPA|EFE|Bloomberg|Anadolu|"
    r"Xinhua|AAP|PA Media|dpa|Shutterstock|iStock|Unsplash|Kyodo|TASS|ANI|PTI"
)
_CREDIT_RE = re.compile(
    r"\bCourtesy of\b|\bPhoto(?:graph)?s?\b|\bImage[:\s]|\bFile photo\b|"
    r"\bScreenshot\b|\bIllustration\b|\bpictured\b|©",
    re.IGNORECASE,
)
_AGENCY_TAIL_RE = re.compile(rf"(?:{_AGENCIES})\s*$")
_AGENCY_ONLY_RE = re.compile(rf"^\s*(?:{_AGENCIES})\s*$")
# Dateline at the very start: "CITY — ", "CITY, REGION — ", "SEOUL (Reuters) - ".
_DATELINE_RE = re.compile(
    r"^\s*[A-ZÀ-Þ][\w .,'’\-]{1,40}?(?:\s*\([^)]{1,30}\))?\s*[—–]\s+"
)


def _is_boilerplate(para: str) -> bool:
    """A short leading paragraph that is a photo caption / agency credit."""
    p = para.strip()
    if not p:
        return True
    if _AGENCY_ONLY_RE.match(p):
        return True
    if len(p) <= 160 and (_CREDIT_RE.search(p) or " / " in p or _AGENCY_TAIL_RE.search(p)):
        return True
    return False


def clean_lead(content: str, max_chars: int = 600) -> str:
    """Return the first substantive prose of `content`, minus caption/credit
    lines and a leading dateline, capped at `max_chars`."""
    if not content:
        return ""
    paras = [p.strip() for p in re.split(r"\n+", content) if p.strip()]

    # Drop leading boilerplate lines, but never consume the whole body.
    while len(paras) > 1 and _is_boilerplate(paras[0]):
        paras.pop(0)

    lead = " ".join(paras)
    lead = _DATELINE_RE.sub("", lead, count=1)
    return lead.strip()[:max_chars]


def build_premise(title: str, content: str = "", max_chars: int = 600) -> str:
    """Compose the text handed to the classifier: title + cleaned lead."""
    title = (title or "").strip()
    lead = clean_lead(content or "", max_chars)
    if lead:
        return f"{title}. {lead}"
    return title
