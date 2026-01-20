import logging
from typing import Any, Dict, Union

from requests import Response

from app.exceptions.service_error import ServiceError

logger = logging.getLogger(__name__)

# TODO Need to break out individual errors and raise them with an appropriate message to make this production quality.
def process_response(response: Response) -> Union[Dict[str, Any], list]:
    """
    Processes HTTP responses and raises errors if needed.
    
    :param response: The response from an HTTP request
    :type response: Response

    :return: The JSON-decoded response data, which could be a dictionary or a list
    :raises ServiceError: When the response status_code is not 200 or 201
    """
    if response.status_code in [200, 201]:
        return response.json()
    
    logger.error(f"API Error: {response.status_code} - {response.text}")
    raise ServiceError(response.json(), response.status_code)

def build_url(*parms: str) -> str:
    """
    Constructs a URL by joining parameters with "/".
    
    :param parms: Variable number of string arguments representing URL segments
    :return: A formatted URL string
    """
    url =  "/".join(str(parm) for parm in parms)
    logger.info(url)
    return url