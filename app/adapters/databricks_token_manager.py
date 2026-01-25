import logging

from app.adapters.base_token_manager import BaseTokenManager
from app.config import DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, DATABRICKS_TOKEN_URL

logger = logging.getLogger(__name__)


class DatabricksTokenManager(BaseTokenManager):
    def __init__(self):
        logger.info(f"TOKEN URL: {DATABRICKS_TOKEN_URL}")
        token_url = DATABRICKS_TOKEN_URL
        client_id = DATABRICKS_CLIENT_ID
        client_secret = DATABRICKS_CLIENT_SECRET
        name = "DATABRICKS_TOKEN_MANAGER"

        super().__init__(name, token_url, client_id, client_secret)