from __future__ import annotations

import pytest
from sqlalchemy import exc

from app.exceptions.forge_error import ForgeError
from app.models.product import Product
from app.models.product_group import ProductGroup
from app.services.product_groups_service import ProductGroupService
from tests._support.fakes import FakeForgeQueryPort


def test_product_group_get_counts() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"status": "Active", "count": 2}]]
    svc = ProductGroupService(sql=fake)
    counts = svc.get_counts()
    assert counts["Active"] == 2
    assert counts["All"] == 2


def test_product_group_get_counts_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError, match="Database error"):
        svc.get_counts()


def test_get_product_groups_attaches_products(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"product_group_id": "pg1", "product_group_name": "Group", "status": "Active"}]]
    svc = ProductGroupService(sql=fake)

    monkeypatch.setattr(
        "app.services.product_groups_service.ProductService.get_products_by_group",
        lambda self, group_id: [Product(product_id="p1", product_name="Prod")],
    )

    groups = svc.get_product_groups()
    assert groups[0].products[0].product_id == "p1"


def test_get_product_groups_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError, match="Database error"):
        svc.get_product_groups()


def test_create_product_group_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductGroupService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "_check_product_group", lambda name: True)
    with pytest.raises(ForgeError):
        svc.create_product_group("Group")


def test_create_product_group_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1]
    svc = ProductGroupService(sql=fake)
    monkeypatch.setattr(svc, "_check_product_group", lambda name: False)
    monkeypatch.setattr(
        svc,
        "get_product_group",
        lambda group_id: ProductGroup(product_group_id=group_id, product_group_name="Group", status="Active"),
    )
    group = svc.create_product_group("Group")
    assert group.product_group_name == "Group"


def test_create_product_group_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    monkeypatch.setattr(svc, "_check_product_group", lambda name: False)
    with pytest.raises(ForgeError, match="Database error"):
        svc.create_product_group("Group")


def test_get_product_group_not_found() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[]]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError):
        svc.get_product_group("pg1")


def test_get_product_group_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"product_group_id": "pg1", "product_group_name": "Group", "status": "Active"}]]
    svc = ProductGroupService(sql=fake)
    monkeypatch.setattr(
        "app.services.product_groups_service.ProductService.get_products_by_group",
        lambda self, group_id: [Product(product_id="p1", product_name="Prod")],
    )
    group = svc.get_product_group("pg1")
    assert group.products[0].product_id == "p1"


def test_get_product_group_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError, match="Database error"):
        svc.get_product_group("pg1")


def test_delete_product_group_not_found() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[]]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError):
        svc.delete_product_group("pg1")


def test_delete_product_group_success() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[("x",)]]
    fake.write_responses = [2, 1]
    svc = ProductGroupService(sql=fake)
    resp = svc.delete_product_group("pg1")
    assert resp["deleted_group"] == 1


def test_delete_product_group_missing_after_delete() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[("x",)]]
    fake.write_responses = [1, 0]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError, match="not found after delete"):
        svc.delete_product_group("pg1")


def test_delete_product_group_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[("x",)]]
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError, match="Failed to delete product group"):
        svc.delete_product_group("pg1")


def test_check_product_group_db_error() -> None:
    fake = FakeForgeQueryPort()
    fake.query_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    with pytest.raises(ForgeError, match="Failed to check product name"):
        svc._check_product_group("Group")


def test_check_product_group_success() -> None:
    fake = FakeForgeQueryPort()
    fake.query_responses = [[("x",)]]
    svc = ProductGroupService(sql=fake)
    assert svc._check_product_group("Group") is True


def test_add_product_to_group_inserts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1]
    svc = ProductGroupService(sql=fake)

    first = ProductGroup.model_construct(
        product_group_id="pg1",
        product_group_name="Group",
        status="Active",
        products=[],
    )
    second = ProductGroup.model_construct(
        product_group_id="pg1",
        product_group_name="Group",
        status="Active",
        products=[Product(product_id="p1", product_name="Prod")],
    )
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: first if not fake.write_calls else second)

    group = svc.add_product_to_group("p1", "pg1")
    assert group.products[0].product_id == "p1"


def test_add_product_to_group_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    svc = ProductGroupService(sql=fake)
    group = ProductGroup.model_construct(
        product_group_id="pg1",
        product_group_name="Group",
        status="Active",
        products=[Product(product_id="p1", product_name="Prod")],
    )
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: group)
    resp = svc.add_product_to_group("p1", "pg1")
    assert resp.product_group_id == "pg1"
    assert fake.write_calls == []


def test_add_product_to_group_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    group = ProductGroup.model_construct(
        product_group_id="pg1",
        product_group_name="Group",
        status="Active",
        products=[],
    )
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: group)
    with pytest.raises(ForgeError, match="Failed to add product"):
        svc.add_product_to_group("p1", "pg1")


def test_add_product_to_group_missing_group(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductGroupService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: None)
    with pytest.raises(ForgeError, match="does not exist"):
        svc.add_product_to_group("p1", "pg1")


def test_remove_product_from_group(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1]
    svc = ProductGroupService(sql=fake)
    group = ProductGroup.model_construct(
        product_group_id="pg1",
        product_group_name="Group",
        status="Active",
        products=[],
    )
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: group)

    resp = svc.remove_product_from_group("p1", "pg1")
    assert resp.product_group_id == "pg1"


def test_remove_product_from_group_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    fake.write_exceptions = [exc.SQLAlchemyError("boom")]
    svc = ProductGroupService(sql=fake)
    group = ProductGroup.model_construct(
        product_group_id="pg1",
        product_group_name="Group",
        status="Active",
        products=[],
    )
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: group)
    with pytest.raises(ForgeError, match="Failed to remove product"):
        svc.remove_product_from_group("p1", "pg1")


def test_remove_product_from_group_missing_group(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ProductGroupService(sql=FakeForgeQueryPort())
    monkeypatch.setattr(svc, "get_product_group", lambda group_id: None)
    with pytest.raises(ForgeError, match="does not exist"):
        svc.remove_product_from_group("p1", "pg1")
