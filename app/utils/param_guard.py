import functools
import inspect
import logging

from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)


def validate_params(*required_params):
    """
    Decorator to ensure required parameters are present.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Works for both bound methods and plain functions.
            try:
                bound = inspect.signature(func).bind_partial(*args, **kwargs)
                provided = dict(bound.arguments)
            except TypeError:
                provided = dict(kwargs)

            for param in required_params:
                if param not in provided or provided[param] is None:
                    logger.error(f"Missing data {provided}")
                    raise ForgeError(f"Missing data ({param})", 400)

            return func(*args, **kwargs)
        return wrapper
    return decorator
