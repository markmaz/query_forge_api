from __future__ import annotations


def test_cohort_ner_success(app, client, auth_headers):
    class _Agent:
        def extract_medical_entities(self, text: str):
            return {"entities": ["x"]}

    app.config["COHORT_NER_AGENT"] = _Agent()

    resp = client.post("/api/v1/cohort_ai/ner", headers=auth_headers, json={"text": "hi"})
    assert resp.status_code == 200
    assert resp.json["entities"] == ["x"]


def test_cohort_ner_requires_auth(client):
    resp = client.post("/api/v1/cohort_ai/ner", json={"text": "hi"})
    assert resp.status_code == 403
