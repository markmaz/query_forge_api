from typing import Dict, List

import requests

from app.config import SIGMA_BASE_URL
from app.decorators.validate import validate_params
from app.models.connection import Connection
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import SIGMA_TOKEN, get_headers


def convert_to_conn(cnx: Dict) -> Connection:
    """
    Utility method to convert a dict to a Connection.

    :param cnx: The dict from the SIGMA API call
    :type cnx: dict

    :return: A Connection object
    """
    return Connection(
        host=cnx["host"], 
        connection_id=cnx["connectionId"], 
        name=cnx["name"], 
        path="", 
        authentication="Basic" if not cnx["useOauth"] else "Oauth", 
        access_token=""
    )

class ConnectionService:
    """
    Service for retrieving Sigma connections.
    """
    
    def get_connections(self) -> List[Dict]:
        """
        Gets all available connections from Sigma.

        :return: A list of dictionary representations of Connection objects.
        """
        response = requests.get(build_url(SIGMA_BASE_URL, "connections"), headers=get_headers(SIGMA_TOKEN))
        data = process_response(response)

        conns = data["entries"]
        connections = [convert_to_conn(cnx) for cnx in conns]
        
        return [c.model_dump() for c in connections] 
    
    @validate_params("organization")
    def get_connection_by_org(self, organization: str) -> List[Dict]:
        """
        Gets a specific connection for an organization (customer).

        :param organization: The organization or customer 
        :type organization: str

        :return: A list of dictionary representations of Connection objects.
        """
        connections = self.get_connections()
        return [cnx for cnx in connections if cnx['name'].startswith(organization)]
    
    @validate_params("host")
    def get_connection_by_host(self, host: str) -> List[Dict]:
        """
        Gets a specific connection by the host name.

        :param host: The host of the workspace server 
        :type host: str

        :return: A list of dictionary representations of Connection objects.
        """
        connections = self.get_connections()
        return [cnx for cnx in connections if cnx['host'].startswith(host)]

    @validate_params("connection_id")
    def get_connection_by_id(self, connection_id: str) -> Dict:
        """
        Gets a specific connection.

        :param connection_id: The connection ID for the connection
        :type connection_id: str

        :return: A dictionary representation of the Connection.
        """
        response = requests.get(build_url(SIGMA_BASE_URL, "connections", connection_id), headers=get_headers(SIGMA_TOKEN))
        data = process_response(response)
        return convert_to_conn(data).model_dump()
    
    # TODO: Need to implement this for completeness - might be needed later
    def create_connection(self, cnx: Connection) -> Dict:
        """
        Placeholder for creating a connection.
        """
        pass

