"""Ingestion feature service composition.

The ingestion feature currently keeps its business logic inside the route
modules because the current slice is focused on canonical namespace ownership.
This module exists so the feature package owns that composition boundary and
can absorb shared orchestration in a later cleanup pass without reviving the
legacy route modules.
"""
