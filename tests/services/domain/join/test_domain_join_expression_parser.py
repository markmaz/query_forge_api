from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.join.domain_join_expression_parser import DomainJoinExpressionParser


def test_parse_json_expr_success() -> None:
    parser = DomainJoinExpressionParser()
    assert parser.parse_json_expr("get_json_object({from}.json_col, '$.key')") == ("from", "json_col", "key")


def test_parse_json_expr_invalid() -> None:
    parser = DomainJoinExpressionParser()
    with pytest.raises(ForgeError):
        parser.parse_json_expr("bad")
