from __future__ import annotations

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.tenancy_bootstrap_service import BootstrapInput, TenancyBootstrapService


class _FakeAdmin:
    def __init__(self):
        self.orgs = {}
        self.datasources = {}
        self.created_org = 0
        self.created_ds = 0
        self.bound = []
        self.org_members = []
        self.ws_members = []

    def get_organization(self, organization_id):
        row = self.orgs.get(organization_id)
        if not row:
            raise ForgeError("Organization not found", status_code=404)
        return row

    def list_organizations(self, **_kwargs):
        return {"rows": list(self.orgs.values())}

    def create_organization(self, req):
        self.created_org += 1
        org_id = req.id or f"org-{self.created_org}"
        row = {"id": org_id, "name": req.name, "slug": req.slug, "is_active": True}
        self.orgs[org_id] = row
        return row

    def list_datasources(self, *, organization_id, **_kwargs):
        rows = [row for row in self.datasources.values() if row.get("organization_id") == organization_id]
        return {"rows": rows}

    def create_datasource(self, *, organization_id, req):
        self.created_ds += 1
        ds_id = self.created_ds
        row = {
            "id": ds_id,
            "organization_id": organization_id,
            "name": req.name,
            "slug": req.slug,
            "type": req.type,
            "is_active": True,
        }
        self.datasources[ds_id] = row
        return row

    def update_workspace_binding(self, *, workspace_id, req):
        row = {"workspace_id": workspace_id, "organization_id": req.organization_id, "datasource_id": req.datasource_id}
        self.bound.append(row)
        return row

    def upsert_organization_membership(self, *, organization_id, req):
        row = {"organization_id": organization_id, "user_id": req.user_id, "role": req.role}
        self.org_members.append(row)
        return row

    def upsert_workspace_membership(self, *, workspace_id, req):
        row = {"workspace_id": workspace_id, "user_id": req.user_id, "role": req.role}
        self.ws_members.append(row)
        return row


def test_bootstrap_creates_org_and_datasource_when_missing():
    admin = _FakeAdmin()
    svc = TenancyBootstrapService(admin=admin)

    out = svc.bootstrap(
        BootstrapInput(
            workspace_id="ws-1",
            organization_name="Acme District",
            datasource_name="Primary",
            datasource_type="snowflake",
        )
    )

    assert out["organization"]["name"] == "Acme District"
    assert out["datasource"]["name"] == "Primary"
    assert out["workspace_binding"]["workspace_id"] == "ws-1"
    assert admin.created_org == 1
    assert admin.created_ds == 1


def test_bootstrap_reuses_existing_org_and_datasource():
    admin = _FakeAdmin()
    admin.orgs["org-1"] = {"id": "org-1", "name": "Acme District", "slug": "acme-district", "is_active": True}
    admin.datasources[10] = {
        "id": 10,
        "organization_id": "org-1",
        "name": "Primary",
        "slug": "primary",
        "type": "snowflake",
        "is_active": True,
    }
    svc = TenancyBootstrapService(admin=admin)

    out = svc.bootstrap(
        BootstrapInput(
            workspace_id="ws-1",
            organization_name="Acme District",
            organization_id="org-1",
            datasource_name="Primary",
            datasource_type="snowflake",
        )
    )

    assert out["organization"]["id"] == "org-1"
    assert out["datasource"]["id"] == 10
    assert admin.created_org == 0
    assert admin.created_ds == 0


def test_bootstrap_assigns_admin_memberships_when_user_provided():
    admin = _FakeAdmin()
    svc = TenancyBootstrapService(admin=admin)

    out = svc.bootstrap(
        BootstrapInput(
            workspace_id="ws-1",
            organization_name="Acme District",
            datasource_name="Primary",
            datasource_type="snowflake",
            admin_user_id="user-1",
        )
    )

    assert out["memberships"]["organization_membership"]["role"] == "org_admin"
    assert out["memberships"]["workspace_membership"]["role"] == "admin"
    assert len(admin.org_members) == 1
    assert len(admin.ws_members) == 1
