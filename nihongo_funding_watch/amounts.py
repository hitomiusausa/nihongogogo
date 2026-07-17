from __future__ import annotations

import re
import unicodedata


AMOUNT = r"[0-9][0-9,]*(?:\.[0-9]+)?(?:億|万|千)?円"

# 「上限」「限度額」などの文脈があるものだけを補助金額として拾う。
# 文脈なしの金額（受講料・参加費など）は営業判断を誤らせるので拾わない。
AMOUNT_PATTERNS = [
    re.compile(r"(?:補助|助成|委託)?(?:上限額?|限度額|基準額|交付額)(?:は|:|：)?[^0-9]{0,8}(" + AMOUNT + ")"),
    re.compile(r"(" + AMOUNT + r")\s*(?:を上限|以内|を限度)"),
    re.compile(r"(?:上限|最大)[^0-9。]{0,8}(" + AMOUNT + ")"),
]

RATE_PATTERN = re.compile(
    r"補助率(?:は|:|：)?[^0-9。]{0,6}([0-9]+分の[0-9]+|[0-9]+/[0-9]+|[0-9]+(?:\.[0-9]+)?%)"
)


def extract_amount(text: str) -> str:
    """補助・委託の金額条件を「上限300万円・補助率1/2」の形で抽出する。見つからなければ空文字。"""
    normalized = unicodedata.normalize("NFKC", text)
    amount = ""
    for pattern in AMOUNT_PATTERNS:
        match = pattern.search(normalized)
        if match:
            amount = normalize_yen(match.group(1).replace(",", ""))
            break

    rate_match = RATE_PATTERN.search(normalized)
    # summary内の区切り文字「/」と衝突しないよう、比率のスラッシュは全角にする。
    rate = rate_match.group(1).replace("/", "／") if rate_match else ""

    parts = []
    if amount:
        parts.append(f"上限{amount}")
    if rate:
        parts.append(f"補助率{rate}")
    return "・".join(parts)


UNIT_MULTIPLIERS = {"億": 100_000_000, "万": 10_000, "千": 1_000}


def normalize_yen(amount: str) -> str:
    """「5000千円」「76676000円」を「500万円」「7667万6000円」に整える（丸めなし）。"""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(億|万|千)?円", amount)
    if not match:
        return amount
    number, unit = match.groups()
    value = float(number) * UNIT_MULTIPLIERS.get(unit or "", 1)
    if value != int(value):
        return amount  # 端数が円未満になる異常値は元の表記のまま
    total = int(value)
    oku, rest = divmod(total, 100_000_000)
    man, en = divmod(rest, 10_000)
    parts = []
    if oku:
        parts.append(f"{oku}億")
    if man:
        parts.append(f"{man}万")
    if en or not parts:
        parts.append(f"{en}")
    return "".join(parts) + "円"
