import os

from dotenv import load_dotenv

from app.adapters.base_token_manager import BaseTokenManager


class SigmaTokenManager(BaseTokenManager):
    def __init__(self):
        load_dotenv()

        token_url= os.getenv("SIGMA_TOKEN_URL") or ""
        client_id = os.getenv("SIGMA_CLIENT_ID")
        client_secret = os.getenv("SIGMA_CLIENT_SECRET")
        name = "SIGMA_TOKEN_MANAGER"

        super().__init__(name, token_url, client_id, client_secret)
