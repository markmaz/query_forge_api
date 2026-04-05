from __future__ import annotations

import logging

from flask_restx import Namespace

logger = logging.getLogger(__name__)
skills_ns = Namespace("skills", description="QueryForge Skills")
