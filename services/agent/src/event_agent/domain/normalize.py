"""Title, URL and identity normalisation.

A leaf module: it imports nothing from the project, which is what lets
``schemas`` depend on it without a cycle. §9.3 requires a stable ``dedupKey``,
and §6.7 優先度4 compares titles, so both live here beside the normalisers they
are built on.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

_WHITESPACE = re.compile(r"\s+")
_DECORATION = re.compile(r"[　-〿！-／：-＠［-｀｛-･!-/:-@\[-`{-~]")
_TRACKING_PREFIXES = ("utm_", "gclid", "fbclid", "mc_cid", "mc_eid")


def normalize_title(title: str) -> str:
    """Fold width, case, punctuation and spacing so near-identical titles match."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    folded = _DECORATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def normalize_url(url: str) -> str:
    """Drop scheme case, ``www.``, tracking query params and trailing slashes."""
    parts = urlsplit(url.strip())
    host = parts.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and not pair.casefold().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), host, path, "&".join(kept), ""))


def compute_dedup_key(
    official_url: str,
    normalized_title: str,
    event_start: datetime | None,
    organizer: str | None,
    deadline: datetime | None = None,
) -> str:
    """Stable identity per §9.3: normalized URL, title, start date and organizer.

    The same event in a different year must produce a different key, so the
    start *date* participates rather than only the month. 実施日が無い告知
    （ビジコン・補助金）は締切の日付で代用し、どちらも無ければ日付なしで束ねる。
    """
    anchor = event_start or deadline
    material = "|".join(
        [
            normalize_url(official_url),
            normalized_title,
            anchor.date().isoformat() if anchor else "",
            normalize_title(organizer or ""),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def title_similarity(left: str, right: str) -> float:
    """Character-level similarity over already-normalized titles (§6.7 優先度4).

    ``difflib`` is stdlib and needs no tokenizer, which matters because the
    titles are mostly Japanese. Very short titles are compared exactly: at
    three or four characters the ratio is dominated by noise.
    """
    if not left or not right:
        return 0.0
    if min(len(left), len(right)) < 6:
        return 1.0 if left == right else 0.0
    matcher = difflib.SequenceMatcher(None, left, right)
    # 安い順に足切りしてから本計算する
    if matcher.real_quick_ratio() < 0.5 or matcher.quick_ratio() < 0.5:
        return matcher.quick_ratio()
    return matcher.ratio()

