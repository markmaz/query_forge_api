
import logging
import os

from dotenv import load_dotenv

from app.adapters.base_token_manager import BaseTokenManager
from app.services.base_service import build_url

logger = logging.getLogger(__name__)


class DatabricksWorkspaceTokenManager(BaseTokenManager):
    def __init__(self, workspace_host: str):
        load_dotenv()

        token_url= build_url(workspace_host, os.getenv("DATABRICKS_WORKSPACE_TOKEN_URL")) or ""
        client_id = os.getenv("DATABRICKS_CLIENT_ID")
        client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")
        name = "DATABRICKS_WORKSPACE_TOKEN_MANAGER"
        
        super().__init__(name, token_url, client_id, client_secret)
