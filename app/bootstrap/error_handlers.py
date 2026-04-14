from __future__ import annotations

from flask import Flask, jsonify

from app.exceptions.forge_error import ForgeError


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ForgeError)
    def handle_service_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response
