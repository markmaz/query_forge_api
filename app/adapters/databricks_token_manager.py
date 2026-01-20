
import logging
import os

from dotenv import load_dotenv

from app.adapters.base_token_manager import BaseTokenManager

logger = logging.getLogger(__name__)


class DatabricksTokenManager(BaseTokenManager):
    def __init__(self):
        load_dotenv()

        token_url= os.getenv("DATABRICKS_TOKEN_URL") or ""
        client_id = os.getenv("DATABRICKS_CLIENT_ID")
        client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")
        name = "DATABRICKS_TOKEN_MANAGER"
        
        super().__init__(name, token_url, client_id, client_secret)
