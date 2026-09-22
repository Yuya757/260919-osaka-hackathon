"""主催者投稿フィード（F-06 / ADR-006）。

投稿は「主催者が書いた告知」であって、AI が検証したイベントではない。だから
``events/`` には書かず、``organizerPosts/`` に派生 Event を埋め込んで保存する。
AI 収集イベントと同じものは重複判定で**結び付けるだけ**で、AI 側の日付や根拠は
書き換えない（run 跨ぎの merge は根拠の run 単位不変条件を壊す）。

投稿本文は信頼できない入力として扱う。発話と同じく、命令様の文は投稿時点で
拒む（ADR-004 決定1）。抽出は決定論的なのでモデルには渡らない。
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlsplit

from event_agent.config import get_settings
from event_agent.domain.dedup import group_duplicates, pick_survivor
from event_agent.extraction.post_text import PostDraft, derive_event_from_post, post_id_for
from event_agent.schemas import (
    ORGANIZER_POST_BODY_MAX,
    ApiEvent,
    OrganizerPost,
    OrganizerPostRequest,
    PostIssue,
    PostPlacement,
)
from event_agent.security import prompt_guard
from event_agent.security.url_guard import ALLOWED_SCHEMES, UnsafeUrl, check_hostname, classify_address
from event_agent.storage.store import effective_placement, feed_order, store

logger = logging.getLogger(__name__)

BOT_ORGANIZER_NAME = "イベント収集ボット"
REJECTED_MESSAGE = "投稿内容を受け付けられませんでした。"
BAD_URL_MESSAGE = "連絡先URLが不正です。http(s) の公開URLを指定してください。"


class PostRejected(Exception):
    """投稿を受け付けない。``message`` は利用者に見せてよい文言だけを持つ。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ----------------------------------------------------------------- guarding


def _check_contact_url(url: str) -> None:
    """URL の形と宛先だけを見る。DNS は引かない（取得はしないので不要）。"""
    parts = urlsplit(url.strip())
    if parts.scheme.casefold() not in ALLOWED_SCHEMES:
        raise PostRejected(BAD_URL_MESSAGE)
    host = (parts.hostname or "").strip().rstrip(".")
    try:
        check_hostname(host)
    except UnsafeUrl as exc:
        raise PostRejected(BAD_URL_MESSAGE) from exc
    literal = classify_address(host)
    if literal not in (None, "not-an-ip"):
        raise PostRejected(BAD_URL_MESSAGE)


def _guard(request: OrganizerPostRequest) -> tuple[OrganizerPostRequest, list[str]]:
    """本文を整え、命令様の投稿を拒む。残る ``flag`` の符号を返す。"""
    _check_contact_url(request.contact_url)
    organizer_name = prompt_guard.sanitize_free_text(
        request.organizer_name, fallback="", max_chars=80
    )
    title = prompt_guard.sanitize_free_text(request.title, fallback="", max_chars=120)
    body = prompt_guard.clean_multiline(request.body, max_chars=ORGANIZER_POST_BODY_MAX)
    findings = prompt_guard.scan(f"{organizer_name}\n{title}\n{body}")
    # sanitize_free_text は命令様の値を空に落とす。空になった＝拒否理由と同じ。
    if prompt_guard.should_block(findings) or not organizer_name or not title or not body:
        logger.warning(
            "PROMPT_INJECTION_BLOCKED_POST codes=%s", prompt_guard.codes(findings)
        )
        raise PostRejected(REJECTED_MESSAGE)
    flags = prompt_guard.codes(findings)
    if flags:
        logger.info("organizer post flagged codes=%s", flags)
    cleaned = OrganizerPostRequest(
        organizerName=organizer_name,
        contactUrl=request.contact_url.strip(),
        title=title,
        body=body,
    )
    return cleaned, flags


# ------------------------------------------------------------------- dedup


def _collected_candidates() -> list[ApiEvent]:
    return [
        e for e in store.list_events() if e.validation_status in ("verified", "partial")
    ]


def link_to_collected_event(event: ApiEvent, candidates: list[ApiEvent]) -> ApiEvent | None:
    """投稿の派生 Event と同じイベントが AI 収集分にあれば、その代表を返す。"""
    if not candidates:
        return None
    groups = group_duplicates(
        [event, *candidates],
        similarity_threshold=get_settings().title_similarity_threshold,
    )
    for group in groups:
        if any(member.event_id == event.event_id for member in group):
            others = [m for m in group if m.event_id != event.event_id]
            return pick_survivor(others) if others else None
    return None


# ------------------------------------------------------------ preview/create


def preview_post(
    request: OrganizerPostRequest, *, now: datetime
) -> tuple[PostDraft, ApiEvent | None]:
    """何も書かずに、抽出結果と指摘だけを返す。"""
    cleaned, _flags = _guard(request)
    draft = derive_event_from_post(cleaned, now=now)
    linked = link_to_collected_event(draft.event, _collected_candidates()) if draft.event else None
    if linked is not None:
        draft.issues.append(
            PostIssue(
                code="DUPLICATE_OF_EVENT",
                severity="warning",
                message=f"AI収集の一覧にある「{linked.title}」と同じイベントのようです。投稿は一覧に結び付けて表示します。",
            )
        )
    return draft, linked


def create_post(
    request: OrganizerPostRequest, *, now: datetime
) -> tuple[OrganizerPost, list[PostIssue]]:
    cleaned, flags = _guard(request)
    draft = derive_event_from_post(cleaned, now=now)
    if not draft.ok() or draft.event is None:
        raise PostRejected(draft.errors[0].message if draft.errors else REJECTED_MESSAGE)
    linked = link_to_collected_event(draft.event, _collected_candidates())
    warnings = list(draft.warnings)
    if linked is not None:
        warnings.append(
            PostIssue(
                code="DUPLICATE_OF_EVENT",
                severity="warning",
                message=f"AI収集の一覧にある「{linked.title}」と同じイベントとして結び付けました。",
            )
        )
    post = OrganizerPost(
        postId=draft.event.event_id,
        origin="organizer",
        organizerName=cleaned.organizer_name,
        contactUrl=cleaned.contact_url,
        title=cleaned.title,
        body=cleaned.body,
        event=draft.event,
        evidence=draft.evidence,
        placement=PostPlacement(),
        linkedEventId=linked.event_id if linked else None,
        linkedDedupKey=linked.dedup_key if linked else None,
        injectionFlags=flags,
        createdAt=now,
        updatedAt=now,
    )
    return store.save_organizer_post(post), warnings


# ------------------------------------------------------------- bot seeding


def _bot_body(event: ApiEvent) -> str:
    """AI 収集イベントを告知文の形にする。締切が未確認なら締切の行を書かない。"""
    from event_agent.extraction.dates import JST

    def fmt(value: datetime, precision: str) -> str:
        local = value.astimezone(JST)
        base = f"{local.year}年{local.month}月{local.day}日"
        return base if precision == "date" else f"{base} {local:%H:%M}"

    lines = [event.summary] if event.summary else []
    held = fmt(event.dates.event_start, event.dates.event_start_precision)
    if event.dates.event_end:
        held += f" 〜 {fmt(event.dates.event_end, 'date')}"
    lines.append(f"開催日: {held}")
    if event.dates.application_deadline is not None:
        lines.append(
            "申込締切: "
            + fmt(event.dates.application_deadline, event.dates.application_deadline_precision)
        )
    if event.location.venue:
        lines.append(f"会場: {event.location.venue}")
    lines.append(f"公式サイト: {event.official_url}")
    return "\n".join(lines)


def seed_bot_posts(events: list[ApiEvent], *, now: datetime) -> list[OrganizerPost]:
    """収集済みイベントをボット投稿としてフィードへ流す。

    フィードが空だと主催者も集まらないので、AI が検証したイベントで埋めておく。
    投稿IDは dedupKey から決まるので、毎日の Run で同じイベントが来ても
    投稿は増えない。Event の写しは AI 側の値そのまま（再抽出しない）。
    """
    seeded: list[OrganizerPost] = []
    for event in events:
        if event.validation_status not in ("verified", "partial"):
            continue
        post = OrganizerPost(
            postId=post_id_for("bot", event.dedup_key),
            origin="bot",
            organizerName=event.organizer or BOT_ORGANIZER_NAME,
            contactUrl=event.official_url,
            title=event.title,
            body=_bot_body(event),
            event=event,
            evidence=[],
            placement=PostPlacement(),
            linkedEventId=event.event_id,
            linkedDedupKey=event.dedup_key,
            injectionFlags=[],
            createdAt=now,
            updatedAt=now,
        )
        seeded.append(store.save_organizer_post(post))
    return seeded


# -------------------------------------------------------------------- feed


def _displayable(post: OrganizerPost, now: datetime) -> bool:
    event = post.event
    if event.validation_status not in ("verified", "partial"):
        return False
    end = event.dates.event_end or event.dates.event_start
    return end >= now


def list_feed(*, now: datetime) -> list[OrganizerPost]:
    """公開中で、開催が終わっていない投稿を、固定 → 優先 → 新しい順で返す。

    主催者投稿が AI 収集イベントに結び付いているとき、同じイベントのボット投稿は
    出さない。主催者本人の告知があるのに、ボットの写しを並べる理由がない。
    """
    posts = [p for p in store.list_organizer_posts(status="published") if _displayable(p, now)]
    claimed = {
        p.linked_dedup_key for p in posts if p.origin == "organizer" and p.linked_dedup_key
    }
    visible = [
        p for p in posts if not (p.origin == "bot" and p.linked_dedup_key in claimed)
    ]
    return feed_order(visible, now=now)


__all__ = [
    "PostRejected",
    "create_post",
    "effective_placement",
    "link_to_collected_event",
    "list_feed",
    "preview_post",
    "seed_bot_posts",
]
