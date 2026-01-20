from __future__ import annotations

import pytest

from app.models.union_spec import UnionSpecV1


def test_union_spec_valid() -> None:
    spec = UnionSpecV1(
        output={"columns": [{"name": "patient_id", "type": "STRING"}]},
        members=[
            {
                "workspace_table_id": 1,
                "select": [{"out": "patient_id", "expr": "from.patient_id"}],
            }
        ],
    )
    assert spec.members[0].workspace_table_id == 1


def test_union_spec_rejects_duplicate_output_names() -> None:
    with pytest.raises(Exception):
        UnionSpecV1(
            output={
                "columns": [
                    {"name": "patient_id", "type": "STRING"},
                    {"name": "patient_id", "type": "STRING"},
                ]
            },
            members=[
                {
                    "workspace_table_id": 1,
                    "select": [{"out": "patient_id", "expr": "from.patient_id"}],
                }
            ],
        )


def test_union_spec_requires_all_outputs() -> None:
    with pytest.raises(Exception):
        UnionSpecV1(
            output={"columns": [{"name": "patient_id", "type": "STRING"}, {"name": "age", "type": "INT"}]},
            members=[
                {
                    "workspace_table_id": 1,
                    "select": [{"out": "patient_id", "expr": "from.patient_id"}],
                }
            ],
        )

