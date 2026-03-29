from __future__ import annotations



def test_base_skill_and_context_importable():
    from app.skills.base import SkillContext

    ctx = SkillContext(workspace_id="ws-1", skill_id="sk-1", execution_id="ex-1")
    assert ctx.workspace_id == "ws-1"
    assert ctx.rows == []
    assert ctx.columns == []


def test_skill_registry_importable():
    from app.skills.registry import SkillRegistry

    assert hasattr(SkillRegistry, "register")
    assert hasattr(SkillRegistry, "get")
    assert hasattr(SkillRegistry, "autodiscover")


def test_email_delivery_skill_type():
    from app.skills.email_delivery import EmailDeliverySkill

    assert EmailDeliverySkill.skill_type == "email_delivery"


def test_email_delivery_registered_after_autodiscover():
    from app.skills.registry import SkillRegistry

    SkillRegistry.autodiscover("app.skills")
    cls = SkillRegistry.get("email_delivery")
    assert cls is not None
    assert cls.skill_type == "email_delivery"


def test_email_delivery_build_html():
    from app.skills.email_delivery import EmailDeliverySkill

    skill = EmailDeliverySkill()
    html = skill._build_html(
        title="Test Report",
        summary="Sales are up.",
        rows=[{"col_a": "v1", "col_b": "v2"}],
        columns=["col_a", "col_b"],
        base_url="http://localhost:3000",
    )
    assert "Test Report" in html
    assert "Sales are up." in html
    assert "col_a" in html
    assert "v1" in html
