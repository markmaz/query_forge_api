from __future__ import annotations

import pytest
from sqlalchemy import exc

from app.exceptions.forge_error import ForgeError
from app.models.product import Product
from app.models.product_role import ProductRole
from app.models.role import Role
from app.services.product_service import ProductService
from tests._support.fakes import FakeForgeQueryPort


def test_product_counts() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"status": "Active", "count": 2}]]
    svc = ProductService(sql=fake)
    counts = svc.get_counts()
    assert counts["Active"] == 2
    assert counts["All"] == 2


def test_product_counts_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError, match="Database error"):
        svc.get_counts()


def test_get_product_not_found() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[]]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError):
        svc.get_product("p1")


def test_check_product_name_exists() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[("x",)]]
    svc = ProductService(sql=fake)
    assert svc.check_product_name_exists("Prod") is True


def test_check_product_name_exists_with_exclude() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[("x",)]]
    svc = ProductService(sql=fake)
    assert svc.check_product_name_exists("Prod", exclude_product_id="p1") is True
    assert fake.query_calls[-1].params["exclude_id"] == "p1"


def test_check_product_name_exists_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError, match="Failed to check product name"):
        svc.check_product_name_exists("Prod")


def test_create_product_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1, 1, 1]
    svc = ProductService(sql=fake)
    monkeypatch.setattr(svc, "check_product_name_exists", lambda name: False)

    resp = svc.create_product("Prod", "pg1", role_ids=["r1"])
    assert resp["product_name"] == "Prod"
    assert len(fake.write_calls) == 3


def test_create_product_duplicate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    svc = ProductService(sql=fake)
    monkeypatch.setattr(svc, "check_product_name_exists", lambda name: True)
    with pytest.raises(ForgeError, match="already exists"):
        svc.create_product("Prod", None)


def test_update_product_updates_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1, 1, 1]
    fake.query_mappings_responses = [[{"role_id": "r1"}]]
    svc = ProductService(sql=fake)
    calls = {"n": 0}

    def _get_product(product_id: str) -> Product:
        calls["n"] += 1
        name = "Old" if calls["n"] == 1 else "New"
        return Product(product_id=product_id, product_name=name, roles=[])

    monkeypatch.setattr(svc, "get_product", _get_product)
    monkeypatch.setattr(svc, "check_product_name_exists", lambda name, exclude_product_id=None: False)

    update = Product(product_name="New", roles=[ProductRole(role=Role(role_id="r2", role_name="Role"), product_role_id="pr2")])
    resp = svc.update_product("p1", update)
    assert resp.product_name == "New"
    assert fake.write_calls


def test_update_product_duplicate_name(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    svc = ProductService(sql=fake)
    monkeypatch.setattr(svc, "get_product", lambda product_id: Product(product_id=product_id, product_name="Old"))
    monkeypatch.setattr(svc, "check_product_name_exists", lambda name, exclude_product_id=None: True)

    update = Product(product_name="New")
    with pytest.raises(ForgeError, match="already exists"):
        svc.update_product("p1", update)


def test_update_product_sql_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    monkeypatch.setattr(svc, "get_product", lambda product_id: Product(product_id=product_id, product_name="Old"))
    update = Product(product_name="Old")
    with pytest.raises(ForgeError, match="Failed to update product"):
        svc.update_product("p1", update)


def test_delete_product_not_found() -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1, 1, 0]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError):
        svc.delete("p1")


def test_delete_product_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError, match="Failed to delete product"):
        svc.delete("p1")


def test_delete_product_success() -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1, 1, 1]
    svc = ProductService(sql=fake)
    res, status = svc.delete("p1")
    assert status == 200
    assert res["message"] == "Product deleted successfully"


def test_rows_to_products_builds_roles() -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    rows = [
        {
            "product_id": "p1",
            "product_name": "Prod",
            "status": "Active",
            "last_update": None,
            "product_role_id": "pr1",
            "role_id": "r1",
            "role_name": "Role",
        }
    ]
    products = svc._rows_to_products(rows, ["p1"])
    assert products[0].roles[0].role.role_id == "r1"


def test_page_product_ids() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"product_id": "p1"}, {"product_id": "p2"}]]
    svc = ProductService(sql=fake)
    ids, has_more = svc._page_product_ids("All", None, 1, "forward")
    assert ids == ["p1"]
    assert has_more is True


def test_get_products_invalid_direction_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    seen = {}

    def _page(status, cursor, limit, direction):
        seen["direction"] = direction
        return [], False

    monkeypatch.setattr(svc, "_page_product_ids", _page)
    monkeypatch.setattr(svc, "_count_products", lambda status: 0)
    products, _next, _prev, _total = svc.get_products(direction="bad")
    assert products == []
    assert seen["direction"] == "forward"


def test_get_products_prev_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "_page_product_ids", lambda status, cursor, limit, direction: (["p1", "p2"], True))
    monkeypatch.setattr(svc, "_count_products", lambda status: 2)
    monkeypatch.setattr(
        svc,
        "_fetch_product_rows",
        lambda ids: [
            {
                "product_id": pid,
                "product_name": f"Prod {pid}",
                "status": "Active",
                "last_update": None,
                "product_role_id": None,
                "role_id": None,
                "role_name": None,
            }
            for pid in ids
        ],
    )

    products, next_cursor, prev_cursor, total = svc.get_products(direction="prev", cursor="p0")
    assert [p.product_id for p in products] == ["p2", "p1"]
    assert next_cursor == "p1"
    assert prev_cursor == "p2"
    assert total == 2


def test_get_products_sql_error(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "_page_product_ids", lambda *_args, **_kwargs: (_ for _ in ()).throw(exc.SQLAlchemyError("boom")))
    with pytest.raises(ForgeError, match="Failed to retrieve products"):
        svc.get_products()


def test_get_products_empty_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "_page_product_ids", lambda status, cursor, limit, direction: ([], False))
    monkeypatch.setattr(svc, "_count_products", lambda status: 5)
    products, next_cursor, prev_cursor, total = svc.get_products()
    assert products == []
    assert next_cursor is None
    assert prev_cursor is None
    assert total == 5


def test_extract_role_ids() -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    items = [
        ProductRole(role=Role(role_id="r1", role_name="Role"), product_role_id="pr1"),
        {"role_id": "r2"},
        {"role": {"role_id": "r3"}},
    ]
    ids = svc._extract_role_ids(items)
    assert ids == {"r1", "r2", "r3"}


def test_get_products_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "_page_product_ids", lambda status, cursor, limit, direction: (["p1"], False))
    monkeypatch.setattr(svc, "_count_products", lambda status: 1)
    monkeypatch.setattr(
        svc,
        "_fetch_product_rows",
        lambda ids: [
            {
                "product_id": "p1",
                "product_name": "Prod",
                "status": "Active",
                "last_update": None,
                "product_role_id": None,
                "role_id": None,
                "role_name": None,
            }
        ],
    )

    products, next_cursor, prev_cursor, total = svc.get_products()
    assert products[0].product_id == "p1"
    assert next_cursor is None
    assert total == 1


def test_get_products_by_group_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "_fetch_product_rows_by_group", lambda gid: [])
    assert svc.get_products_by_group("pg1") == []


def test_get_products_by_group_success() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [
        [
            {
                "product_id": "p1",
                "product_name": "Prod",
                "status": "Active",
                "last_update": None,
                "product_role_id": None,
                "role_id": None,
                "role_name": None,
            }
        ]
    ]
    svc = ProductService(sql=fake)
    products = svc.get_products_by_group("pg1")
    assert products[0].product_id == "p1"


def test_get_products_by_group_sql_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError, match="Database error"):
        svc.get_products_by_group("pg1")


def test_get_product_success() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [
        [
            {
                "product_id": "p1",
                "product_name": "Prod",
                "status": "Active",
                "last_update": None,
                "product_role_id": None,
                "role_id": None,
                "role_name": None,
            }
        ]
    ]
    svc = ProductService(sql=fake)
    product = svc.get_product("p1")
    assert product.product_id == "p1"


def test_get_product_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    with pytest.raises(ForgeError, match="Database error"):
        svc.get_product("p1")


def test_create_product_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductService(sql=fake)
    monkeypatch.setattr(svc, "check_product_name_exists", lambda name: False)
    with pytest.raises(ForgeError, match="Database error"):
        svc.create_product("Prod", None)


def test_count_products_helper() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"cnt": 3}]]
    svc = ProductService(sql=fake)
    assert svc._count_products("All") == 3


def test_fetch_product_rows_by_group_helper() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"product_id": "p1"}]]
    svc = ProductService(sql=fake)
    rows = svc._fetch_product_rows_by_group("pg1")
    assert rows[0]["product_id"] == "p1"


def test_fetch_product_rows_empty() -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    assert svc._fetch_product_rows([]) == []


def test_page_product_ids_with_cursor() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"product_id": "p2"}]]
    svc = ProductService(sql=fake)
    ids, has_more = svc._page_product_ids("All", "p1", 10, "forward")
    assert ids == ["p2"]
    assert has_more is False


def test_extract_role_ids_empty() -> None:
    svc = ProductService(sql=FakeForgeQueryPort())
    assert svc._extract_role_ids([]) == set()


def test_extract_role_ids_attr_object() -> None:
    class Holder:
        def __init__(self, role_id: str) -> None:
            self.role_id = role_id

    svc = ProductService(sql=FakeForgeQueryPort())
    ids = svc._extract_role_ids([Holder("r9")])
    assert ids == {"r9"}
