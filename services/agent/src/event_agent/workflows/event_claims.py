"""主催者がイベントを申請し、本人確認のうえ直す（ADR-013）。

ログインは無い。代わりに、アプリが発行した確認コードをイベントページに書いて
もらい、エージェントがそのページを読みに行って確かめる。ページを書き換えられる
人＝主催者、とみなす。確かめられたら編集用の鍵を渡し、サーバーはハッシュだけを持つ。

ページは外部入力なので、コードが含まれるかを文字列で見るだけで、中身をモデルにも
画面にも渡さない。取得は収集と同じ page_fetcher（SSRF 対策済み）を通す。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from event_agent.clients.page_fetcher import FetchedPage, page_fetcher
from event_agent.schemas import (
    ApiEvent,
    EventClaim,
    EventClaimStartResponse,
    EventClaimVerifyResponse,
    OrganizerEdit,
    OrganizerEditValues,
)
from event_agent.security import prompt_guard
from event_agent.security.url_guard import UnsafeUrl, check_hostname, classify_address
from event_agent.storage.store import store

# 読み違えやすい文字（0/O、1/I/L）を外す
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CLAIM_TTL = timedelta(hours=24)
TOKEN_TTL = timedelta(days=30)
MAX_ATTEMPTS = 10

MESSAGES = {
    "verified": "確認できました。このイベントの情報を直せます。",
    "code_not_found": "イベントページに確認コードが見つかりませんでした。ページに書いて公開してから、もう一度お試しください。",
    "page_unavailable": "イベントページを読めませんでした。時間をおいてもう一度お試しください。",
    "expired": "確認コードの期限が切れました。はじめからやり直してください。",
    "too_many_attempts": "確認の回数が上限に達しました。はじめからやり直してください。",
}


class ClaimError(Exception):
    """申請・編集を受け付けられない。``status`` は HTTP の状態、``message`` は画面に出す文。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _new_code() -> str:
    part = lambda: "".join(secrets.choice(_ALPHABET) for _ in range(4))  # noqa: E731
    return f"CHO-{part()}-{part()}"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _page_urls(event: ApiEvent) -> list[str]:
    urls = [event.official_url]
    if event.application_url and event.application_url != event.official_url:
        urls.append(event.application_url)
    return [url for url in urls if url.startswith("https://")]


def start_claim(event_id: str, *, now: datetime) -> EventClaimStartResponse:
    event = store.get_event(event_id)
    if event is None or event.validation_status not in ("verified", "partial"):
        raise ClaimError(404, "イベントが見つかりません。")
    pages = _page_urls(event)
    if not pages:
        raise ClaimError(422, "このイベントには確認に使える https のページがありません。")
    claim = EventClaim(
        claimId=str(uuid4()),
        eventId=event.event_id,
        code=_new_code(),
        pageUrls=pages,
        createdAt=now,
        expiresAt=now + CLAIM_TTL,
    )
    store.save_claim(claim)
    return EventClaimStartResponse(
        claimId=claim.claim_id,
        eventId=claim.event_id,
        code=claim.code,
        pageUrls=claim.page_urls,
        expiresAt=claim.expires_at,
    )


def _result(claim: EventClaim, status: str, **extra) -> EventClaimVerifyResponse:
    return EventClaimVerifyResponse(
        claimId=claim.claim_id, status=status, message=MESSAGES[status], **extra
    )


async def verify_claim(claim_id: str, *, now: datetime) -> EventClaimVerifyResponse:
    """イベントページを読み、確認コードがあれば鍵を渡す。鍵はこの応答でしか出ない。"""
    claim = store.get_claim(claim_id)
    if claim is None:
        raise ClaimError(404, "申請が見つかりません。")
    if claim.verified_at is not None:
        # 鍵は一度しか渡さない（ハッシュしか持っていない）
        raise ClaimError(409, "この申請はすでに確認済みです。鍵を無くした場合は、はじめからやり直してください。")
    if claim.expires_at <= now:
        return _result(claim, "expired")
    if claim.attempts >= MAX_ATTEMPTS:
        return _result(claim, "too_many_attempts")
    claim = claim.model_copy(update={"attempts": claim.attempts + 1})

    read_any = False
    found_on: str | None = None
    for url in claim.page_urls:
        page = await page_fetcher.fetch(url)
        if not isinstance(page, FetchedPage):
            continue
        read_any = True
        if claim.code in page.text.upper():
            found_on = url
            break

    if found_on is None:
        store.save_claim(claim)
        return _result(claim, "code_not_found" if read_any else "page_unavailable")

    token = secrets.token_urlsafe(32)
    claim = claim.model_copy(
        update={
            "verified_at": now,
            "verified_page_url": found_on,
            "edit_token_hash": _hash(token),
            "token_expires_at": now + TOKEN_TTL,
        }
    )
    store.save_claim(claim)
    return _result(claim, "verified", editToken=token, tokenExpiresAt=claim.token_expires_at)


# ------------------------------------------------------------------ 編集


def _check_url(url: str) -> str:
    """申込ページの URL。形と宛先だけを見る（取得はしない）。"""
    parts = urlsplit(url.strip())
    if parts.scheme.casefold() != "https":
        raise ClaimError(422, "申込ページは https の URL を入れてください。")
    host = (parts.hostname or "").strip().rstrip(".")
    try:
        check_hostname(host)
    except UnsafeUrl as exc:
        raise ClaimError(422, "申込ページの URL を確認してください。") from exc
    if classify_address(host) not in (None, "not-an-ip"):
        raise ClaimError(422, "申込ページの URL を確認してください。")
    return url.strip()


def _clean_values(values: OrganizerEditValues, event: ApiEvent, *, now: datetime) -> OrganizerEditValues:
    def text(value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        cleaned = prompt_guard.sanitize_free_text(value, fallback="", max_chars=limit).strip()
        return cleaned or None

    station = text(values.nearest_station, 40)
    if station:
        station = station.removesuffix("駅").strip() or None
    deadline = values.application_deadline
    if deadline is not None:
        if deadline.tzinfo is None:
            raise ClaimError(422, "申込締切にはタイムゾーン付きの日時を入れてください。")
        if deadline < now:
            raise ClaimError(422, "申込締切が過去の日時です。")
        start = event.dates.event_start
        if start is not None and deadline > start:
            raise ClaimError(422, "申込締切が開催日より後になっています。")
    url = _check_url(values.application_url) if values.application_url else None
    return OrganizerEditValues(
        nearestStation=station,
        venue=text(values.venue, 120),
        applicationDeadline=deadline,
        applicationUrl=url,
    )


def edit_event(
    claim_id: str, edit_token: str, values: OrganizerEditValues, *, now: datetime
) -> ApiEvent:
    """鍵を確かめて、主催者の値をイベントに持たせる。前の編集に上書きで足す。"""
    claim = store.get_claim(claim_id)
    if (
        claim is None
        or claim.edit_token_hash is None
        or not hmac.compare_digest(claim.edit_token_hash, _hash(edit_token))
    ):
        raise ClaimError(403, "編集の鍵が正しくありません。")
    if claim.token_expires_at is None or claim.token_expires_at <= now:
        raise ClaimError(403, "編集の鍵の期限が切れました。はじめからやり直してください。")
    event = store.get_event(claim.event_id)
    if event is None:
        raise ClaimError(404, "イベントが見つかりません。")

    cleaned = _clean_values(values, event, now=now)
    previous = event.organizer_edit.values if event.organizer_edit else OrganizerEditValues()
    merged = OrganizerEditValues(
        nearestStation=cleaned.nearest_station or previous.nearest_station,
        venue=cleaned.venue or previous.venue,
        applicationDeadline=cleaned.application_deadline or previous.application_deadline,
        applicationUrl=cleaned.application_url or previous.application_url,
    )
    edit = OrganizerEdit(
        verifiedAt=claim.verified_at or now,
        pageUrl=claim.verified_page_url or claim.page_urls[0],
        editedAt=now,
        values=merged,
    )
    return store.update_event(event.model_copy(update={"organizer_edit": edit}))
