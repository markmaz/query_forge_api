import logging
import threading
import time

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

TOKEN_REFRESH_ERRORS = (requests.RequestException, ValueError)


class BaseForgeTokenManager:
    def __init__(self, name: str, token_url: str, client_id: str, client_secret: str, scope: str = "all-apis"):
        load_dotenv()
        self._token_manager_name = name

        self._token = None
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope

    def refresh_token(self):
        try:
            response = requests.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": self._scope,
                },
            )
            if response.status_code == 200:
                self._token = response.json().get("access_token")
                logging.info(f"{self._token_manager_name} token refreshed.")
            else:
                logging.error(f"Failed to refresh token: {response.text}")
        except TOKEN_REFRESH_ERRORS as e:
            logging.error(f"Error refreshing token: {e}")

    def start_auto_refresh(self, interval=3000):
        logging.info(f"{self._token_manager_name} token autorefresh started.")

        def refresh_loop():
            while True:
                self.refresh_token()
                time.sleep(interval)

        threading.Thread(target=refresh_loop, daemon=True).start()

    @property
    def token(self):
        if self._token:
            return self._token
        else:
            self.refresh_token()
            return self._token
    
    @token.setter
    def token(self, value):
        if not value:
            raise ValueError("Token cannot be empty")
        self._token  = value

    
    @property
    def token_manager_name(self):
        return self._token_manager_name
    
    @token_manager_name.setter
    def token_manager_name(self, value):
        if not value:
            raise ValueError("Name cannot be empty")
        
        self._token_manager_name = value
    
    @property
    def client_id(self):
        return self._client_id
    
    @client_id.setter
    def client_id(self, value):
        if not value:
            raise ValueError("Client ID cannot be empty")
        
        self._client_id = value

    @property
    def client_secret(self):
        return self._client_secret
    
    @client_secret.setter
    def client_secret(self, value):
        if not value:
            raise ValueError("Client Secret cannot be empty")
        
        self._client_secret = value

    def fetch_forge_token(self):
        return self.token

    def forge_auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
