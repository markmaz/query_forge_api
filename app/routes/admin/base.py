from __future__ import annotations

import logging

from flask_restx import Namespace

admin_ns = Namespace("admin", description="Admin operations")
logger = logging.getLogger(__name__)
