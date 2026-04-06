from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[.,]+")
_WHITESPACE_RE = re.compile(r"\s+")
_CODE2_RE = re.compile(r"^[A-Za-z]{2}$")
_CODE3_RE = re.compile(r"^[A-Za-z]{3}$")

_COUNTRY_ALIAS_TO_ISO2: Dict[str, str] = {
    "united states": "US",
    "us": "US",
    "u s": "US",
    "u.s": "US",
    "u.s.": "US",
    "america": "US",
    "mexico": "MX",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "u k": "GB",
    "u.k": "GB",
    "u.k.": "GB",
    "britain": "GB",
    "great britain": "GB",
    "england": "GB",
    "france": "FR",
    "germany": "DE",
    "spain": "ES",
    "italy": "IT",
    "india": "IN",
    "china": "CN",
    "japan": "JP",
    "australia": "AU",
    "brazil": "BR",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "south korea": "KR",
    "korea": "KR",
}

_ISO3_TO_ISO2: Dict[str, str] = {
    "USA": "US",
    "MEX": "MX",
    "CAN": "CA",
    "GBR": "GB",
    "FRA": "FR",
    "DEU": "DE",
    "ESP": "ES",
    "ITA": "IT",
    "IND": "IN",
    "CHN": "CN",
    "JPN": "JP",
    "AUS": "AU",
    "BRA": "BR",
    "ARG": "AR",
    "COL": "CO",
    "CHL": "CL",
    "KOR": "KR",
}


def normalize_country_values(value_or_values: Any) -> List[str]:
    """
    Normalize user-entered country values to ISO-3166-1 alpha-2 codes.

    Returns a deduped list of uppercase ISO2 values. Unknown values return [].
    """
    values = _as_values(value_or_values)
    if not values:
        return []

    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        code = _normalize_single_country_value(raw)
        if code is None:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    logger.debug("country_normalizer resolved values=%s input=%s", out, values)
    return out


def resolve_country_from_db(sql: ForgeQueryPort, normalized_text: str) -> Optional[str]:
    """
    Optional DB fallback to resolve country aliases/codes.
    If reference tables are unavailable, returns None.
    """
    token = _normalize_text(normalized_text)
    if token == "":
        return None

    queries = [
        (
            """
            SELECT country_iso2
            FROM country_reference
            WHERE LOWER(country_iso2) = :value
               OR LOWER(country_iso3) = :value
               OR LOWER(country_name) = :value
               OR LOWER(country_alias) = :value
            LIMIT 1
            """,
            {"value": token},
        ),
        (
            """
            SELECT iso2
            FROM ref_country
            WHERE LOWER(iso2) = :value
               OR LOWER(iso3) = :value
               OR LOWER(name) = :value
               OR LOWER(alias) = :value
            LIMIT 1
            """,
            {"value": token},
        ),
    ]

    for query, params in queries:
        try:
            rows = sql.execute_query_mappings(query, params)
        except SQLAlchemyError:
            continue
        for row in rows:
            code = str(row.get("country_iso2") or row.get("iso2") or "").strip().upper()
            if _CODE2_RE.match(code):
                logger.debug("country_normalizer db_fallback matched token=%s code=%s", token, code)
                return code
    return None


def is_country_iso2_column(col_meta: Dict[str, Any]) -> bool:
    semantic_type = str(col_meta.get("semantic_type") or "").strip().lower()
    if semantic_type in {"country_iso2", "iso2_country", "country_code2"}:
        return True

    column_name = str(col_meta.get("column_name") or "").strip().lower()
    data_type = str(col_meta.get("data_type") or "").strip().lower()
    is_text = _is_textual_type(data_type)
    if column_name == "birth_country" and is_text:
        return True
    if column_name.endswith("_country") and is_text:
        return True
    return False


def _normalize_single_country_value(raw_value: str) -> Optional[str]:
    raw = str(raw_value or "").strip()
    if raw == "":
        return None

    if _CODE2_RE.match(raw):
        return raw.upper()

    if _CODE3_RE.match(raw):
        code3 = raw.upper()
        mapped = _ISO3_TO_ISO2.get(code3)
        if mapped:
            return mapped

    token = _normalize_text(raw)
    if token == "":
        return None

    mapped = _COUNTRY_ALIAS_TO_ISO2.get(token)
    if mapped:
        return mapped

    return None


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _as_values(value_or_values: Any) -> List[str]:
    if value_or_values is None:
        return []
    if isinstance(value_or_values, list):
        return [str(item).strip() for item in value_or_values if str(item).strip()]
    token = str(value_or_values).strip()
    if token == "":
        return []
    return [token]


def _is_textual_type(data_type: str) -> bool:
    token = str(data_type or "").strip().lower()
    return any(
        t in token
        for t in (
            "string",
            "varchar",
            "char",
            "text",
        )
    )


__all__ = [
    "is_country_iso2_column",
    "normalize_country_values",
    "resolve_country_from_db",
]
