from enum import Enum


class UserStatus(str, Enum):
    INVITED = "Invited"
    ACTIVE = "Active"
    INACTIVE = "Inactive"

class ProductStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"

class ProductGroupStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"