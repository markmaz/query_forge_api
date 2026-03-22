from enum import Enum


class UserStatus(str, Enum):
    INVITED = "Invited"
    ACTIVE = "Active"
    INACTIVE = "Inactive"
