import functools
import logging

from app.exceptions.service_error import ServiceError

logger = logging.getLogger(__name__)

def validate_params(*required_params):
    """
    Decorator to ensure required parameters are present.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Convert positional args to kwargs if possible
            func_params = func.__code__.co_varnames  # Get function argument names
            all_kwargs = {**dict(zip(func_params[1:], args)), **kwargs}  # Merge args into kwargs
            
            for param in required_params:
                if param not in all_kwargs or all_kwargs[param] is None:
                    logger.error(f"Missing data {all_kwargs}")
                    raise ServiceError(f"Missing data ({param})", 400)
            
            return func(self, *args, **kwargs)
        return wrapper
    return decorator
