"""Pure parsing helpers shared by ingestion and analysis layers."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
MONTHS = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}
MONTH_NAMES = {number: name.capitalize() for name, number in MONTHS.items()}


class ParseError(ValueError):
    """Raised when financial input cannot be parsed without guessing."""


def normalize_text(value: object) -> str:
    text = str(value or "").strip().casefold()
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def parse_money(value: object) -> Decimal:
    """Parse common BR/international money forms without falling back to zero."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)

    raw = str(value or "").strip()
    if not raw:
        raise ParseError("valor monetário vazio")

    negative_parentheses = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9,.-]", "", raw.strip("()"))
    if cleaned.count("-") > 1 or ("-" in cleaned and not cleaned.startswith("-")):
        raise ParseError(f"sinal monetário inválido: {raw!r}")

    sign = "-" if cleaned.startswith("-") or negative_parentheses else ""
    cleaned = cleaned.lstrip("-")
    if not cleaned or not re.search(r"\d", cleaned):
        raise ParseError(f"valor monetário inválido: {raw!r}")

    if "," in cleaned and "." in cleaned:
        decimal_sep = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        normalized = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in cleaned:
        normalized = _normalize_single_separator(cleaned, ",")
    elif "." in cleaned:
        normalized = _normalize_single_separator(cleaned, ".")
    else:
        normalized = cleaned

    try:
        amount = Decimal(f"{sign}{normalized}")
    except InvalidOperation as exc:
        raise ParseError(f"valor monetário inválido: {raw!r}") from exc
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _normalize_single_separator(value: str, separator: str) -> str:
    parts = value.split(separator)
    if len(parts) == 2 and len(parts[1]) in (1, 2):
        return f"{parts[0]}.{parts[1]}"
    if len(parts) > 1 and len(parts[-1]) == 2:
        return f"{''.join(parts[:-1])}.{parts[-1]}"
    return "".join(parts)


def format_money(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def parse_period(value: object) -> tuple[int, int]:
    raw = str(value or "").strip()
    match = re.fullmatch(r"([A-Za-zÀ-ÿ]{3,})/(\d{4})", raw)
    if match:
        month = MONTHS.get(normalize_text(match.group(1))[:3])
        if month:
            return int(match.group(2)), month

    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})", raw)
    if match and 1 <= int(match.group(2)) <= 12:
        return int(match.group(1)), int(match.group(2))
    raise ParseError(f"período inválido: {raw!r}; esperado Mmm/AAAA")


def format_period(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month]}/{year}"


def period_key(value: object) -> tuple[int, int]:
    try:
        return parse_period(value)
    except ParseError:
        return 0, 0


def month_distance(older: object, newer: object) -> int:
    older_year, older_month = parse_period(older)
    newer_year, newer_month = parse_period(newer)
    return max(0, (newer_year - older_year) * 12 + newer_month - older_month)


def normalize_date(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, pattern).strftime("%d/%m/%Y")
        except ValueError:
            continue
    raise ParseError(f"data inválida: {raw!r}")


def parse_installment(value: object) -> tuple[int, int] | None:
    raw = str(value or "").strip()
    if not raw or normalize_text(raw) in {"unica", "à vista", "a vista"}:
        return None
    match = re.fullmatch(r"0*(\d+)\s*/\s*0*(\d+)", raw)
    if not match:
        return None
    current, total = int(match.group(1)), int(match.group(2))
    if current < 1 or total < 1 or current > total:
        return None
    return current, total


def normalized_installment(value: object) -> str:
    parsed = parse_installment(value)
    if not parsed:
        return ""
    current, total = parsed
    return f"{current:02d}/{total:02d}"
