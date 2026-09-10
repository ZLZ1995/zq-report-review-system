"""ASGI entrypoint."""

from .api import create_app

app = create_app()
