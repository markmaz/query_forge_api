from celery import shared_task
from sqlalchemy import create_engine

from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.config import MYSQL_URL  # e.g. mysql+pymysql://user:pass@host/db
from app.services.catalog.catalog_sync import reconcile_columns, sync_dbx_catalog_snapshot
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder


def build_executor_for_workspace(workspace_id: str) -> DatabricksSQLExecutor:
    ctx = WorkspaceContextBuilder().build(workspace_id)
    return ctx.sql_exec


@shared_task(bind=True, name="catalog.sync_workspace")
def sync_workspace_catalog(self, workspace_id: str, schema_name: str = "asset"):
    engine = create_engine(MYSQL_URL, pool_pre_ping=True)

    # however you build your executor (token manager already in your app)
    executor: DatabricksSQLExecutor = build_executor_for_workspace(workspace_id)

    snap = sync_dbx_catalog_snapshot(
        engine=engine,
        executor=executor,
        workspace_id=workspace_id,
        schema_name=schema_name,
        catalog_name=None,  # discover via current_catalog()
    )
    recon = reconcile_columns(engine=engine, workspace_id=workspace_id)

    return {"snapshot": snap, "reconcile": recon}
