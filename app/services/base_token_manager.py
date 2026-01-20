from flask import current_app

SIGMA_TOKEN = "SIGMA_TOKEN_MANAGER"
DATABRICKS_TOKEN = "DATABRICKS_TOKEN_MANAGER"

def get_token(token_manager: str):
    """
    Generic Token manager - gets or refreshes the token from the given system.

    :param token_manager: The name of the token manager. Should be one of the constants in this class. 
    :type token_manager: str

    Returns:
        The token from the token manager.
    Raises:
        RuntimeError: when the given token_manager does not exist or isn't configured in the system.
    """
    with current_app.app_context():
        token_manager = current_app.config.get(token_manager)
        if token_manager:
            return token_manager.token
        raise RuntimeError(f"{token_manager} is not configured in Flask app.")

def get_headers(token_manager: str):
    """
    Helper method to set the Bearer information for an HTTP request. It gets the correct token for the given system.

    :param token_manager: The name of the token_manager. Should be one of the constants in this class.
    :type token_manager: str

    Returns:
        dict (Header paramerters)
    """
    return {
            "Authorization": f"Bearer {get_token(token_manager=token_manager)}",
            "Content-Type": "application/json",
        }