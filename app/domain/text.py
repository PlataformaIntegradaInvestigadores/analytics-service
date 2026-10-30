"""Language-neutral preparation; no learned transformation or language guessing."""

import re
import unicodedata

from app.domain.common import fingerprint

VERSION = "unicode-title-abstract-v1"


def prepare_text(title: str, abstract: str | None) -> dict:
    def clean(value):
        return " ".join(unicodedata.normalize("NFKC", value or "").split())

    title, abstract = clean(title), clean(abstract)
    text = "\n".join(part for part in (title, abstract) if part)
    tokens = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text.casefold(), re.UNICODE)
    return {
        "text": text,
        "tokens": tokens,
        "token_count": len(tokens),
        "text_sha256": fingerprint(text),
        "duplicate_key": fingerprint(text.casefold()),
        "has_abstract": bool(abstract),
    }
