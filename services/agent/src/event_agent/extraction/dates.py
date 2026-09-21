"""Japanese date and deadline parsing (§6.5, §6.6).

Two rules from the requirements drive the design:

* 「年を一意に確定できない場合は日時を null にし、推測しない」 — a date with no
  year is only completed from an explicit year found elsewhere on the page, and
  only when the page shows exactly one candidate year.
* Precision must reflect what the page actually said. A date with no time is
  ``date``; we never invent 00:00 or 23:59 and call it a datetime.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 「申込締切」として採用してよいラベル
APPLICATION_LABELS = (
    "申込締切", "申込み締切", "申し込み締切", "応募締切", "エントリー締切",
    "参加申込締切", "申込期限", "応募期限", "エントリー期限", "申込〆切", "参加登録締切",
)
# 締切ではあるが「申込締切」ではないラベル。混同すると §13.2 の締切正確率が落ちる。
NON_APPLICATION_DEADLINE_LABELS = (
    "早割", "早期割引", "早期申込", "作品提出", "作品提出締切", "提出締切",
    "予稿締切", "原稿締切", "登壇応募", "スポンサー申込", "支払期限", "キャンセル期限",
)
EVENT_DATE_LABELS = ("開催日", "開催日時", "会期", "日程", "開催期間", "イベント日")

_YEAR = r"(?P<year>20\d{2})\s*[年/\-\.]"
_MD = r"(?P<month>\d{1,2})\s*[月/\-\.]\s*(?P<day>\d{1,2})\s*日?"
_TIME = r"(?:\s*\(?[月火水木金土日]\)?)?(?:\s*(?P<hour>\d{1,2})\s*[:時]\s*(?P<minute>\d{2})分?)?"

_FULL = re.compile(_YEAR + r"\s*" + _MD + _TIME)
_NO_YEAR = re.compile(_MD + _TIME)
_YEAR_ONLY = re.compile(r"20\d{2}")


@dataclass(frozen=True)
class ParsedDate:
    value: datetime
    precision: str  # "datetime" | "date"
    snippet: str


def normalize(text: str) -> str:
    """NFKC so full-width digits parse, and unify separators."""
    return unicodedata.normalize("NFKC", text)


def page_years(text: str) -> set[int]:
    return {int(m.group(0)) for m in _YEAR_ONLY.finditer(text)}


def _build(
    year: int, month: int, day: int, hour: str | None, minute: str | None, snippet: str
) -> ParsedDate | None:
    try:
        if hour is not None and minute is not None:
            value = datetime(year, month, day, int(hour), int(minute), tzinfo=JST)
            return ParsedDate(value, "datetime", snippet)
        value = datetime(year, month, day, tzinfo=JST)
        return ParsedDate(value, "date", snippet)
    except ValueError:
        return None  # 2月30日 のような存在しない日付


def parse_date(fragment: str, *, fallback_year: int | None) -> ParsedDate | None:
    """Parse the first date in ``fragment``.

    When the fragment carries no year, ``fallback_year`` is used — and the
    caller only supplies one when the page states exactly one year. Otherwise
    the result is None and the field stays null, per §6.5.
    """
    text = normalize(fragment)
    match = _FULL.search(text)
    if match:
        return _build(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            match.group("hour"),
            match.group("minute"),
            match.group(0).strip(),
        )
    match = _NO_YEAR.search(text)
    if match and fallback_year is not None:
        return _build(
            fallback_year,
            int(match.group("month")),
            int(match.group("day")),
            match.group("hour"),
            match.group("minute"),
            match.group(0).strip(),
        )
    return None


def parse_range(fragment: str, *, fallback_year: int | None) -> tuple[ParsedDate | None, ParsedDate | None]:
    """Parse ``A〜B`` style ranges. The end inherits the start's year."""
    text = normalize(fragment)
    for separator in ("〜", "～", "~", "-", "–", "—", "から"):
        if separator in text:
            left, _, right = text.partition(separator)
            start = parse_date(left, fallback_year=fallback_year)
            if start is None:
                continue
            end = parse_date(right, fallback_year=start.value.year)
            return start, end
    return parse_date(text, fallback_year=fallback_year), None


def find_labelled(text: str, labels: tuple[str, ...]) -> list[tuple[str, str]]:
    """Return ``(label, rest-of-line)`` for lines carrying one of ``labels``.

    Lines are the unit because these pages render as ``ラベル: 値`` rows.
    """
    found: list[tuple[str, str]] = []
    for raw_line in normalize(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for label in labels:
            index = line.find(label)
            if index >= 0:
                found.append((label, line[index + len(label) :].lstrip(" :：　-ー")))
                break
    return found


def find_application_deadline(text: str, *, fallback_year: int | None) -> ParsedDate | None:
    """Pick the 申込締切 only, ignoring 早割 / 作品提出 and friends (§6.5)."""
    for label, rest in find_labelled(text, APPLICATION_LABELS):
        # 「早割申込締切」のように非申込ラベルが同じ行にあるものは採らない
        line = label + rest
        if any(bad in line for bad in NON_APPLICATION_DEADLINE_LABELS):
            continue
        parsed = parse_date(rest, fallback_year=fallback_year)
        if parsed is not None:
            return parsed
    return None


def find_event_dates(
    text: str, *, fallback_year: int | None
) -> tuple[ParsedDate | None, ParsedDate | None]:
    for _label, rest in find_labelled(text, EVENT_DATE_LABELS):
        start, end = parse_range(rest, fallback_year=fallback_year)
        if start is not None:
            return start, end
    return None, None
