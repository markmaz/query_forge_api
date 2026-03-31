"""Exports feature route schemas.

The exports feature currently delegates request validation to downstream
services, so there are no Flask-RESTX models to centralize yet. This module
exists so the migrated feature follows the same contract as the other
feature-owned route packages.
"""
