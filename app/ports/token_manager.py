from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ForgeTokenPort(Protocol):
    def refresh_token(self):
        """"""
    
    def start_auto_refresh(self, interval: 3000):
        """"""
    
    def token(self):
        """"""