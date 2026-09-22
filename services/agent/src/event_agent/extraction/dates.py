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
from typing import NamedTuple
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# 「申込締切」として採用してよいラベル。より具体的な語を先に置く
# （`find_labelled` は行に最初に当たったラベルを採る）。
# 末尾の「募集期間」以降は期間で書かれる募集（アクセラ・共創に多い）で、
# 範囲の終わりが締切になる。裸の「締切」は最後の手段。
APPLICATION_LABELS = (
    "申込締切", "申込み締切", "申し込み締切", "応募締切", "エントリー締切",
    "参加申込締切", "申込期限", "応募期限", "エントリー期限", "申込〆切", "参加登録締切",
    "募集締切", "募集期限", "応募・提出締切", "出展申込締切",
    "募集期間", "応募期間", "エントリー期間", "締切",
)
# 締切ではあるが「申込締切」ではないラベル。混同すると §13.2 の締切正確率が落ちる。
NON_APPLICATION_DEADLINE_LABELS = (
    "早割", "早期割引", "早期申込", "作品提出", "作品提出締切", "提出締切",
    "予稿締切", "原稿締切", "登壇応募", "スポンサー申込", "支払期限", "キャンセル期限",
)
EVENT_DATE_LABELS = ("開催日", "開催日時", "会期", "日程", "開催期間", "イベント日")

# 締切と実施日のあいだの節目（ジャンル拡張計画）。値が取れたものだけ持つ
MILESTONE_LABELS = (
    "エントリー開始", "募集開始", "受付開始", "説明会", "キックオフ",
    "書類選考結果通知", "一次選考通過", "一次審査", "二次審査",
    "プレゼン審査", "最終審査会", "最終審査", "結果発表", "表彰式", "審査結果",
    # アクセラ・共創（事前調査: Creww は「選考期間」「面談期間」で書く）
    "選考期間", "審査期間", "面談期間", "採択発表", "採択企業発表",
    "プログラム期間", "Demo Day", "デモデイ",
)


# ジャンル固有の値として拾うラベル（ジャンル拡張計画 段階2）。
# 値は行をそのまま持ち、構造化はしない。日付のラベルはここに入れない。
COMMON_ATTRIBUTE_LABELS = ("参加費", "対象", "応募資格", "参加資格", "定員")
CONTEST_ATTRIBUTE_LABELS = ("賞金", "副賞", "最優秀賞", "表彰")
PROGRAM_ATTRIBUTE_LABELS = (
    "支援内容", "提供リソース", "出資", "出資額", "募集テーマ", "募集企業",
    "対象ステージ", "採択予定数", "活動場所",
)


class LabelSet(NamedTuple):
    """ジャンルごとのラベル表（ジャンル拡張計画の事前調査）。

    「提出締切」はハッカソンでは作品提出であって申込締切ではないが、ビジコンでは
    「ビジネスプランシート応募・提出締切」が本物の応募締切である。同じ語で扱いが
    逆になるので、除外語は kind ごとに持つ。
    """

    deadline: tuple[str, ...]
    exclude: tuple[str, ...]
    event_dates: tuple[str, ...]
    milestones: tuple[str, ...]
    attributes: tuple[str, ...] = COMMON_ATTRIBUTE_LABELS


_CONTEST_EXCLUDE = tuple(
    label
    for label in NON_APPLICATION_DEADLINE_LABELS
    # ビジコンでは「提出締切」は応募そのもの。早割と支払いだけ除く
    if label not in ("作品提出", "作品提出締切", "提出締切", "予稿締切", "原稿締切", "登壇応募")
)

# アクセラ・共創の「実施」はプログラム期間や Demo Day で、会場に集まる日は
# 書かれないことが多い。期間が書いてあればその開始を実施日にする。
_PROGRAM_DATE_LABELS = EVENT_DATE_LABELS + ("プログラム期間", "Demo Day", "デモデイ")

_CONTEST_ATTRIBUTES = CONTEST_ATTRIBUTE_LABELS + COMMON_ATTRIBUTE_LABELS
_PROGRAM_ATTRIBUTES = PROGRAM_ATTRIBUTE_LABELS + CONTEST_ATTRIBUTE_LABELS + COMMON_ATTRIBUTE_LABELS

LABEL_SETS: dict[str, LabelSet] = {
    "hackathon": LabelSet(APPLICATION_LABELS, NON_APPLICATION_DEADLINE_LABELS, EVENT_DATE_LABELS, MILESTONE_LABELS, _CONTEST_ATTRIBUTES),
    "contest": LabelSet(APPLICATION_LABELS, _CONTEST_EXCLUDE, EVENT_DATE_LABELS + ("最終審査会", "最終審査"), MILESTONE_LABELS, _CONTEST_ATTRIBUTES),
    "accelerator": LabelSet(APPLICATION_LABELS, _CONTEST_EXCLUDE, _PROGRAM_DATE_LABELS, MILESTONE_LABELS, _PROGRAM_ATTRIBUTES),
    "cocreation": LabelSet(APPLICATION_LABELS, _CONTEST_EXCLUDE, _PROGRAM_DATE_LABELS, MILESTONE_LABELS, _PROGRAM_ATTRIBUTES),
}


def labels_for(kind: str) -> LabelSet:
    return LABEL_SETS.get(kind, LABEL_SETS["hackathon"])

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


def find_labelled(text: str, labels: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """Return ``(label, rest-of-line, whole-line)`` for lines carrying a label.

    Lines are the unit because these pages render as ``ラベル: 値`` rows.

    The whole line is returned as well, and callers must use it for exclusion
    checks: labels nest, so 「早期申込締切」 contains 「申込締切」 and
    「スポンサー申込締切」 does too. Reconstructing the line from label+rest
    drops the prefix and makes those look like a plain 申込締切.
    """
    found: list[tuple[str, str, str]] = []
    for raw_line in normalize(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for label in labels:
            index = line.find(label)
            if index >= 0:
                found.append((label, line[index + len(label) :].lstrip(" :：　-ー"), line))
                break
    return found


def deadline_from_fragment(fragment: str, *, fallback_year: int | None) -> ParsedDate | None:
    """締切の値を読む。範囲（「募集期間 A〜B締切」）なら終わりが締切。

    開始日を締切として登録すると、まだ応募できるものを「終了」に見せてしまう。
    """
    start, end = parse_range(fragment, fallback_year=fallback_year)
    if end is not None:
        return end
    return start


# 「募集期間 A〜B」は締切を名指ししていない。名指しの締切が同じページにあるなら
# そちらが正しい（AUBA は「応募期間」を先に書き、後から「応募締切 …23:59」と書く）。
PERIOD_LABELS = ("募集期間", "応募期間", "エントリー期間")
BARE_DEADLINE_LABELS = ("締切",)


def _deadline_tiers(labels: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """締切ラベルを確度の順に分ける。名指し → 裸の「締切」→ 期間。"""
    weak = set(PERIOD_LABELS) | set(BARE_DEADLINE_LABELS)
    named = tuple(label for label in labels if label not in weak)
    bare = tuple(label for label in labels if label in BARE_DEADLINE_LABELS)
    period = tuple(label for label in labels if label in PERIOD_LABELS)
    return tuple(tier for tier in (named, bare, period) if tier)


def find_application_deadline(
    text: str, *, fallback_year: int | None, kind: str = "hackathon"
) -> ParsedDate | None:
    """Pick the 申込締切 only, ignoring 早割 / 作品提出 and friends (§6.5).

    除外語は ``kind`` で変わる（ジャンル拡張計画）。
    """
    labels = labels_for(kind)
    for tier in _deadline_tiers(labels.deadline):
        for _label, rest, line in find_labelled(text, tier):
            # 行全体で判定する。「早期申込締切」「スポンサー申込締切」は
            # 「申込締切」を含むので、接頭辞まで見ないと除外できない。
            if any(bad in line for bad in labels.exclude):
                continue
            parsed = deadline_from_fragment(rest, fallback_year=fallback_year)
            if parsed is not None:
                return parsed
    return None


def _milestone_label(line: str, label: str) -> str:
    """行の見出しをそのまま節目の名前にする。

    ラベル表は部分一致なので、「一次審査結果発表」の行は「一次審査」で当たる。
    そのまま出すと審査の日か発表の日か分からなくなるため、行の見出し側を使う。
    日付を含む（＝見出しと値が同じ行に続いている）場合は当たったラベルに戻す。
    """
    head = re.split(r"[:：]", line, maxsplit=1)[0].strip(" 　-ー・■●▼▶>【】[]")
    if label in head and 1 <= len(head) <= 40 and not re.search(r"\d", head):
        return head
    return label


def find_milestones(
    text: str,
    *,
    fallback_year: int | None,
    kind: str = "hackathon",
    limit: int = 5,
) -> list[tuple[str, ParsedDate]]:
    """節目（一次選考通過、最終審査会、結果発表…）を拾う。値が読めたものだけ。

    2 軸（締切・実施日）と同じ日になる節目も落とさない。「実施日 = 最終審査会」の
    ように、その日が何の日かを名前が伝えるため。重ねて見せないのは表示側の仕事。
    """
    found: list[tuple[str, ParsedDate]] = []
    seen: set[str] = set()
    for label, rest, line in find_labelled(text, labels_for(kind).milestones):
        if label in seen:
            continue
        parsed = parse_date(rest, fallback_year=fallback_year)
        if parsed is None:
            continue
        seen.add(label)
        found.append((_milestone_label(line, label), parsed))
        if len(found) >= limit:
            break
    # 時系列として出すので日付順。本文の並びは節目の順とは限らない
    return sorted(found, key=lambda pair: pair[1].value)


def find_attributes(
    text: str, *, kind: str = "hackathon", limit: int = 10
) -> dict[str, str]:
    """ジャンル固有の値を行から拾う（ジャンル拡張計画 段階2）。

    値は行に書かれたまま持ち、構造化も換算もしない（「賞金」を数値にしない）。
    文章になっている行（「賞金については後日お知らせします。」）は捨てる:
    一覧や詳細に並べる値であって、本文の写しではない。
    """
    found: dict[str, str] = {}
    for label, rest, line in find_labelled(text, labels_for(kind).attributes):
        if label in found:
            continue
        # 「対象」は「対象ステージ」の一部でもある。区切りが続く行だけ採る
        after = line.find(label) + len(label)
        if after < len(line) and line[after] not in " 　:：-ー・|/\t":
            continue
        value = rest.strip(" 　:：-ー・")
        if not 1 <= len(value) <= 60 or value.endswith(("。", "ます", "です", "ください")):
            continue
        found[label] = value
        if len(found) >= limit:
            break
    return found


def find_event_dates(
    text: str, *, fallback_year: int | None, kind: str = "hackathon"
) -> tuple[ParsedDate | None, ParsedDate | None]:
    for _label, rest, _line in find_labelled(text, labels_for(kind).event_dates):
        start, end = parse_range(rest, fallback_year=fallback_year)
        if start is not None:
            return start, end
    return None, None
