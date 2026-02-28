from __future__ import annotations

import json

from app.ports.sql_executor import ExecuteResult
from app.services.nlp_review_service import NLPReviewService
from tests._support.fakes import FakeSQLExecutor


def test_review_queue_round_trip() -> None:
    sql = FakeSQLExecutor()
    sql.insert_responses = [ExecuteResult(rowcount=1, lastrowid=100)]
    sql.query_mappings_responses = [
        [
            {
                "id": 100,
                "workspace_id": "ws-1",
                "prompt": "Find all the students named Holden",
                "model_version": "model-v1",
                "prediction_json": json.dumps({"slots": {"names": [{"value": "Holden"}]}}),
                "corrected_json": None,
                "status": "pending",
                "created_at": None,
                "updated_at": None,
            }
        ],
        [
            {
                "id": 100,
                "workspace_id": "ws-1",
                "prompt": "Find all the students named Holden",
                "model_version": "model-v1",
                "prediction_json": json.dumps({"slots": {"names": [{"value": "Holden"}]}}),
                "corrected_json": json.dumps(
                    {
                        "entities": [{"start": 28, "end": 34, "label": "VALUE_LITERAL"}],
                        "cats": {"intent_lookup_by_name": 1.0},
                    }
                ),
                "status": "approved",
                "created_at": None,
                "updated_at": None,
            }
        ],
        [
            {
                "id": 100,
                "workspace_id": "ws-1",
                "prompt": "Find all the students named Holden",
                "model_version": "model-v1",
                "prediction_json": json.dumps({"slots": {"names": [{"value": "Holden"}]}}),
                "corrected_json": json.dumps(
                    {
                        "entities": [{"start": 28, "end": 34, "label": "VALUE_LITERAL"}],
                        "cats": {"intent_lookup_by_name": 1.0},
                    }
                ),
                "status": "approved",
                "created_at": None,
                "updated_at": None,
            }
        ],
    ]
    sql.write_responses = [1]

    svc = NLPReviewService(sql=sql)

    created = svc.enqueue(
        workspace_id="ws-1",
        prompt="Find all the students named Holden",
        model_version="model-v1",
        prediction_json={"slots": {"names": [{"value": "Holden"}]}},
    )
    assert created["id"] == 100
    assert created["status"] == "pending"

    patched = svc.patch_item(
        workspace_id="ws-1",
        item_id=100,
        status="approved",
        corrected={
            "entities": [{"start": 28, "end": 34, "label": "VALUE_LITERAL"}],
            "cats": {"intent_lookup_by_name": 1.0},
        },
    )
    assert patched["status"] == "approved"

    exported = svc.export_item_jsonl(workspace_id="ws-1", item_id=100)
    line = exported["line"]
    assert line["text"] == "Find all the students named Holden"
    assert line["cats"]["intent_lookup_by_name"] == 1.0
    assert line["entities"][0]["label"] == "VALUE_LITERAL"
