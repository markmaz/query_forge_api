from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedUCTable:
    catalog_name: str
    schema_name: str
    table_name: str
    model_table_name: str
    variant_code: Optional[str]
    is_qe: bool


def parse_uc_full_name(full_name: str) -> ParsedUCTable:
    catalog_name, schema_name, table_name = _split_full_name(full_name)
    model_table_name, variant_code = _split_model_and_variant(table_name)
    return ParsedUCTable(
        catalog_name=catalog_name,
        schema_name=schema_name,
        table_name=table_name,
        model_table_name=model_table_name,
        variant_code=variant_code,
        is_qe=_is_qe_variant(variant_code),
    )


def _split_full_name(full_name: str) -> tuple[str, str, str]:
    parts = str(full_name or "").strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.table, got: {full_name}")
    return parts[0], parts[1], parts[2]


def _split_model_and_variant(table_name: str) -> tuple[str, str | None]:
    tokens = table_name.split("_")
    if not tokens:
        return table_name, None

    suffix = tokens[-1].lower()
    if suffix in {"noqe", "withqe", "qe", "witheq"}:
        return "_".join(tokens[:-1]) or table_name, tokens[-1]

    if len(tokens) >= 3:
        lowered = [token.lower() for token in tokens]
        if "union" in lowered:
            split_idx = lowered.index("union")
            return "_".join(tokens[:split_idx]) or table_name, "_".join(tokens[split_idx:])
        return "_".join(tokens[:-1]) or table_name, tokens[-1]

    return table_name, None


def _is_qe_variant(variant_code: str | None) -> bool:
    return str(variant_code or "").lower() in {"qe", "withqe", "witheq"}
