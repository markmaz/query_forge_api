from __future__ import annotations

import re
from typing import Tuple

from app.exceptions.forge_error import ForgeError

_JSON_EXPR_PATTERN = re.compile(r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$")


class DomainJoinExpressionParser:
    def parse_json_expr(self, expr: str) -> Tuple[str, str, str]:
        match = _JSON_EXPR_PATTERN.match(expr)
        if not match:
            raise ForgeError(
                "joinSpec expr must match get_json_object({from|to}.<col>, '$.<key>')",
                status_code=400,
            )
        return match.group(1), match.group(2), match.group(3)
