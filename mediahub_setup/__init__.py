"""MediaHub Setup — web wizard installer for a self-hosted *arr stack."""

__version__ = "0.1.0"

from .app import create_app

__all__ = ["__version__", "create_app"]
