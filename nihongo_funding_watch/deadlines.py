from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
ERA_START_YEARS = {
    "令和": 2018,
    "平成": 1988,
}
DEADLINE_WORDS = (
    "締切",
    "締め切り",
    "〆切",
    "期限",
    "提出期限",
    "応募期限",
    "申請期限",
    "募集期限",
    "受付期間",
    "募集期間",
    "必着",
    "まで",
)
BEFORE_DEADLINE_WORDS = (
    "締切",
    "締め切り",
    "〆切",
    "期限",
    "提出期限",
    "応募期限",
    "申請期限",
    "募集期限",
    "受付期間",
    "募集期間",
    "公募期間",
    "申込",
    "申し込み",
    "応募",
    "提出",
)
AFTER_DEADLINE_WORDS = (
    "締切",
    "締め切り",
    "〆切",
    "期限",
    "必着",
    "まで",
)


def extract_deadline(text: str, *, today: date | None = None) -> date | None:
    if not text:
        return None
    today = today or datetime.now(JST).date()
    candidates: list[date] = []

    for match in re.finditer(r"(20\d{2})[年/-]\s*(\d{1,2})[月/-]\s*(\d{1,2})日?", text):
        found = make_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found and is_deadline_context(text, match.start(), match.end()):
            candidates.append(found)

    for match in re.finditer(r"(令和|平成)\s*(元|\d{1,2})年\s*(\d{1,2})月\s*(\d{1,2})日?", text):
        era = match.group(1)
        era_year = 1 if match.group(2) == "元" else int(match.group(2))
        found = make_date(
            ERA_START_YEARS[era] + era_year,
            int(match.group(3)),
            int(match.group(4)),
        )
        if found and is_deadline_context(text, match.start(), match.end()):
            candidates.append(found)

    for match in re.finditer(r"(?<!\d)(\d{1,2})月\s*(\d{1,2})日", text):
        month = int(match.group(1))
        day = int(match.group(2))
        context_year = infer_nearby_year(text, match.start(), match.end())
        years = (context_year,) if context_year else (today.year, today.year + 1)
        for year in years:
            found = make_date(year, month, day)
            if not found or not is_deadline_context(text, match.start(), match.end()):
                continue
            if context_year or found >= today:
                candidates.append(found)
                break

    future = sorted(candidate for candidate in candidates if candidate >= today)
    return future[0] if future else (sorted(candidates)[-1] if candidates else None)


def is_deadline_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 36) : start]
    after = text[end : min(len(text), end + 42)]
    if any(word in before for word in BEFORE_DEADLINE_WORDS):
        return True

    word_positions = [after.find(word) for word in AFTER_DEADLINE_WORDS if word in after]
    if not word_positions:
        return False
    first_word = min(word_positions)
    next_date = next_date_position(after)
    return next_date is None or first_word < next_date


def make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def next_date_position(text: str) -> int | None:
    patterns = [
        r"20\d{2}[年/-]\s*\d{1,2}[月/-]\s*\d{1,2}日?",
        r"(令和|平成)\s*(元|\d{1,2})年\s*\d{1,2}月\s*\d{1,2}日?",
        r"(?<!\d)\d{1,2}月\s*\d{1,2}日",
    ]
    positions = [
        match.start()
        for pattern in patterns
        for match in re.finditer(pattern, text)
    ]
    return min(positions) if positions else None


def infer_nearby_year(text: str, start: int, end: int) -> int | None:
    window = text[max(0, start - 80) : min(len(text), end + 20)]
    western = list(re.finditer(r"20\d{2}年", window))
    if western:
        return int(western[-1].group(0)[:4])

    eras = list(re.finditer(r"(令和|平成)\s*(元|\d{1,2})年", window))
    if not eras:
        return None
    match = eras[-1]
    era = match.group(1)
    era_year = 1 if match.group(2) == "元" else int(match.group(2))
    return ERA_START_YEARS[era] + era_year


def days_until(deadline: date | None, *, today: date | None = None) -> int | None:
    if not deadline:
        return None
    today = today or datetime.now(JST).date()
    return (deadline - today).days


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
