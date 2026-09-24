"""本人確認した主催者が直した値を、イベントに当て直す（ADR-013）。

収集は毎朝やり直すので、主催者の値はイベント本体ではなく ``organizerEdit`` に
持ち、保存のたびにここで当て直す。値を足すだけで、収集した値から推測はしない。
"""

from __future__ import annotations

from event_agent.schemas import ApiEvent


def apply_organizer_edit(event: ApiEvent) -> ApiEvent:
    """``organizerEdit`` の値でイベントを上書きしたコピー。編集が無ければそのまま。

    申込締切は主催者本人の値なので、締切だけが欠けて ``partial`` だったイベントは
    ``verified`` に上げる。締切が開催日より後になる値は、ここに来る前に弾いている。
    """
    edit = event.organizer_edit
    if edit is None:
        return event
    values = edit.values
    location = event.location
    if values.nearest_station or values.venue:
        location = location.model_copy(
            update={
                "nearest_station": values.nearest_station or location.nearest_station,
                "venue": values.venue or location.venue,
            }
        )
    dates = event.dates
    status = event.validation_status
    if values.application_deadline is not None:
        dates = dates.model_copy(
            update={
                "application_deadline": values.application_deadline,
                "application_deadline_precision": "datetime",
            }
        )
        if status == "partial" and dates.event_start is not None:
            status = "verified"
    return event.model_copy(
        update={
            "location": location,
            "dates": dates,
            "application_url": values.application_url or event.application_url,
            "validation_status": status,
        }
    )
