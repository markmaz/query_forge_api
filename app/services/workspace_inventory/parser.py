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
    parts = full_name.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.table, got: {full_name}")
    catalog, schema, table = parts

    tokens = table.split("_")
    variant = None
    model_tokens = tokens

    last = tokens[-1].lower() if tokens else ""
    if last in {"noqe", "withqe", "qe", "witheq"}:
        variant = tokens[-1]
        model_tokens = tokens[:-1]
    elif len(tokens) >= 3:
        lowered = [t.lower() for t in tokens]
        if "union" in lowered:
            i = lowered.index("union")
            variant = "_".join(tokens[i:])
            model_tokens = tokens[:i]
        else:
            variant = tokens[-1]
            model_tokens = tokens[:-1]

    model = "_".join(model_tokens) if model_tokens else table
    is_qe = (variant or "").lower() in {"qe", "withqe", "witheq"}

    return ParsedUCTable(
        catalog_name=catalog,
        schema_name=schema,
        table_name=table,
        model_table_name=model,
        variant_code=variant,
        is_qe=is_qe,
    )