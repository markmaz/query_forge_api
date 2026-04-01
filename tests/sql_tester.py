from app.services.query_forge.service import QueryForgeService


class FakeDomainResolver:
    def resolve(self, domain_id: int) -> str:
        # what your real resolver returns should already be safe (catalog.schema.table or view)
        return "main.asset.claims_header"


class FakeExecutor:
    def execute(self, sql: str, params=None):
        return {"ok": True, "sql": sql, "params": params}


def test_compile_with_aliases_where_sorting():
    svc = QueryForgeService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver())

    q = {
            "version": 1,
            "domainId": 2,
            "columns": [
                {
                    "modelColumnId": 1445,
                    "columnName": "episode_end",
                    "modelTableName": "physical_therapy",
                    "fullName": "analytics.asset.physical_therapy_events_az",
                    "alias": "Episode End"
                },
                {
                    "modelColumnId": 1446,
                    "columnName": "episode_id",
                    "modelTableName": "physical_therapy",
                    "fullName": "analytics.asset.physical_therapy_events_az",
                    "alias": "Episode ID"
                },
                {
                    "modelColumnId": 1447,
                    "columnName": "episode_start",
                    "modelTableName": "physical_therapy",
                    "fullName": "analytics.asset.physical_therapy_events_az",
                    "alias": "Episode Start"
                },
                {
                    "modelColumnId": 1452,
                    "columnName": "facility_longitude",
                    "modelTableName": "physical_therapy",
                    "fullName": "analytics.asset.physical_therapy_events_az",
                    "alias":None
                },
                {
                    "modelColumnId": 1453,
                    "columnName": "facility_name",
                    "modelTableName": "physical_therapy",
                    "fullName": "analytics.asset.physical_therapy_events_az",
                    "alias": None
                }
            ],
            "filters": {
                "type": "group",
                "id": "root",
                "match": "and",
                "children": [
                    {
                        "type": "group",
                        "id": "8woidwft",
                        "match": "and",
                        "children": [
                            {
                                "type": "condition",
                                "id": "67y56rzk",
                                "field": "episode_end",
                                "op": "gt",
                                "value": "12/01/2001"
                            },
                            {
                                "type": "condition",
                                "id": "rj9n6mmg",
                                "field": "episode_start",
                                "op": "lt",
                                "value": "12/01/2021"
                            }
                        ]
                    },
                    {
                        "type": "group",
                        "id": "swyf6jtd",
                        "match": "and",
                        "children": [
                            {
                                "type": "condition",
                                "id": "va6qcbdr",
                                "field": "facility_longitude",
                                "op": "equals",
                                "value": "10"
                            }
                        ]
                    }
                ]
            },
            "aggs": {
                "enabled": True,
                "metrics": [
                    {
                        "id": "gxc8z2g2",
                        "fn": "count",
                        "column": None,
                        "label": "row count"
                    }
                ],
                "groupBy": [
                    "episode_end",
                    "episode_id",
                    "episode_start"
                ]
            },
            "sorting": [
                {
                    "columnName": "episode_end",
                    "dir": "asc"
                },
                {
                    "columnName": "facility_longitude",
                    "dir": "asc"
                }
            ],
            "value_overrides": {
                "a": None,
                "b": None,
                "c": None
            },
            "meta": {
                "createdAt": "2026-01-02T21:13:50.564Z",
                "updatedAt": "2026-01-02T21:15:39.257Z",
                "prompt": ""
            }
        }

    compiled = svc.run(q, "preview")
    print(compiled.get("sql"))
    print(compiled.get("params"))

test_compile_with_aliases_where_sorting()