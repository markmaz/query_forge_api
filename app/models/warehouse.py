from enum import Enum
from typing import Dict, Optional

from dotenv import load_dotenv
from flask_restx import Namespace, fields

from app.models.cluster_size_enum import ClusterSize
from app.models.warehouse_type_enum import WarehouseType

load_dotenv()

warehouse_ns = Namespace("warehouses", description="Warehouse related operations")

class Warehouse:
    odbc_params_model = warehouse_ns.model("ODBCParams", {
    "hostname": fields.String(required=True, description="ODBC hostname"),
    "path": fields.String(required=True, description="ODBC path"),
    "protocol": fields.String(required=True, description="ODBC protocol"),
    "port": fields.Integer(required=True, description="ODBC port"),
    })
    
    warehouse_model = warehouse_ns.model(
        "Warehouse",
        {
            "warehouse_id": fields.String(required=True, description="Unique identifier for the workspace"),
            "name": fields.String(required=True, description="Name of the workspace"),
            "auto_stop_minutes": fields.String(required=False, description="Test"),
            "cluster_size": fields.String(required=True, description=""),
            "min_number_clusters": fields.String(required=True, description=""),
            "max_number_clusters": fields.String(required=True, description=""),
            "creator_name" : fields.String(required=True, description=""),
            "enable_serverless_compute": fields.Boolean(required=True, description=""),
            "server_type": fields.String(required=True, description=""),
            "jdbc_url": fields.String(required=False, description=""),
            "odbc_params": fields.Nested(odbc_params_model, required=False)
        },
    )

    def __init__(self, warehouse_id: Optional[str] = "", name: Optional[str] = "", cluster_size: Optional[str] = ClusterSize.XXS.value, auto_stop_minutes: Optional[int] = 120,  min_number_clusters: Optional[int] = 0, max_number_clusters: Optional[str] = 1, 
                 creator_name: Optional[str] = "", enable_serverless_compute: Optional[bool] = False, server_type: Optional[str] = WarehouseType.PRO.value, 
                 jdbc_url: Optional[str] = None, odbc_params: Optional[Dict]= None) -> None:
        
        self._warehouse_id = warehouse_id
        self._name = name
        self._cluster_size = cluster_size
        
        self._auto_stop_minutes = auto_stop_minutes
        self._min_number_clusters = min_number_clusters
        self._max_number_clusters = max_number_clusters
        self._jdbc_url = jdbc_url
        self._odbc_params = odbc_params or {}
        self._creator_name = creator_name
        self._enable_serverless_compute = enable_serverless_compute
        self._server_type = server_type

    @property
    def warehouse_id(self):
        return self._warehouse_id

    @warehouse_id.setter
    def warehouse_id(self, value):
        if not isinstance(value, str):
            raise ValueError("warehouse_id must be a string")
        self._warehouse_id = value

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if not isinstance(value, str):
            raise ValueError("name must be a string")
        self._name = value

    @property
    def cluster_size(self):
        return self._cluster_size

    @cluster_size.setter
    def cluster_size(self, value):
        if not isinstance(value, ClusterSize):
            raise ValueError(f"cluster_size must be one of {list(ClusterSize)}")
        self._cluster_size = value

    @property
    def auto_stop_minutes(self):
        return self._auto_stop_minutes

    @auto_stop_minutes.setter
    def auto_stop_minutes(self, value):
        if not isinstance(value, str) or not value.isdigit():
            raise ValueError("auto_stop_minutes must be a numeric string")
        self._auto_stop_minutes = value

    @property
    def min_number_clusters(self):
        return self._min_number_clusters

    @min_number_clusters.setter
    def min_number_clusters(self, value):
        if not isinstance(value, int):
            raise ValueError("min_number_clusters must be an integer")
        self._min_number_clusters = value

    @property
    def max_number_clusters(self):
        return self._max_number_clusters

    @max_number_clusters.setter
    def max_number_clusters(self, value):
        if not isinstance(value, int):
            raise ValueError("max_number_clusters must be an integer")
        self._max_number_clusters = value

    @property
    def creator_name(self):
        return self._creator_name

    @creator_name.setter
    def creator_name(self, value):
        if not isinstance(value, str):
            raise ValueError("creator_name must be a string")
        self._creator_name = value

    @property
    def enable_serverless_compute(self):
        return self._enable_serverless_compute

    @enable_serverless_compute.setter
    def enable_serverless_compute(self, value):
        if not isinstance(value, bool):
            raise ValueError("enable_serverless_compute must be a boolean")
        self._enable_serverless_compute = value

    @property
    def server_type(self):
        return self._server_type

    @server_type.setter
    def server_type(self, value):
        if not isinstance(value, str):
            raise ValueError("server_type must be a string")
        self._server_type = value

    @property
    def jdbc_url(self):
        return self._jdbc_url

    @jdbc_url.setter
    def jdbc_url(self, value):
        if value is not None and not isinstance(value, str):
            raise ValueError("jdbc_url must be a string or None")
        self._jdbc_url = value

    @property
    def odbc_params(self):
        return self._odbc_params

    @odbc_params.setter
    def odbc_params(self, value):
        if not isinstance(value, dict):
            raise ValueError("odbc_params must be a dictionary")
        self._odbc_params = value

    def to_dict(self):
        return {
            "warehouse_id": self.warehouse_id,
            "name": self.name,
            "cluster_size": (
                self.cluster_size.value
                if isinstance(self.cluster_size, Enum)
                else self.cluster_size
            ),
            "auto_stop_minutes": self.auto_stop_minutes,
            "min_number_clusters": self.min_number_clusters,
            "max_number_clusters": self.max_number_clusters,
            "creator_name": self.creator_name,
            "enable_serverless_compute": self.enable_serverless_compute,
            "server_type": self.server_type,
            "jdbc_url": self.jdbc_url,
            "odbc_params": self.odbc_params,
    }
    
    def to_create(self):
        return {
            "name": self._name,
            "cluster_size": self._cluster_size,
            "auto_stop_mins": self._auto_stop_minutes,
            "min_num_clusters": self._min_number_clusters,
            "max_num_clusters": self._max_number_clusters,
            "creator_name": self._creator_name,
            "enable_serverless_compute": f"{self._enable_serverless_compute}",
            "server_type": self._server_type,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Warehouse":
        """Creates a Warehouse instance from a dictionary."""
        
        def safe_enum(enum_cls, value, default=None):
            try:
                return enum_cls(value)
            except ValueError:
                return default or list(enum_cls)[0]  # default to the first enum value

        return cls(
            warehouse_id=data.get("id", ""),
            name=data.get("name", ""),
            auto_stop_minutes=data.get("auto_stop_mins", 120),
            cluster_size=safe_enum(ClusterSize, data.get("cluster_size", ClusterSize.XXS.value)),
            enable_serverless_compute=data.get("enable_serverless_compute", False),
            jdbc_url=data.get("jdbc_url"),
            max_number_clusters=data.get("max_num_clusters", 1),
            min_number_clusters=data.get("min_num_clusters", 0),
            odbc_params=data.get("odbc_params", {}),
            creator_name=data.get("creator_name", ""),
            server_type=safe_enum(WarehouseType, data.get("warehouse_type", WarehouseType.PRO.value)).value
        )

