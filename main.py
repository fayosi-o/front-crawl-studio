"""Long Catch: a local 3D front-crawl stroke explorer.

Run with ``python main.py`` and open http://127.0.0.1:8080.
"""

import os
from collections.abc import Mapping

from nicegui import app, ui

import long_catch.app  # noqa: F401  (registers the page)
from long_catch.auth import AuthConfig, PrivateAccess


def server_address(environ: Mapping[str, str] = os.environ) -> tuple[str, int]:
    port = environ.get('PORT')
    if port:
        return '0.0.0.0', int(port)
    return '127.0.0.1', 8080


if __name__ in {'__main__', '__mp_main__'}:
    host, port = server_address()
    auth = AuthConfig.from_env()
    app.add_middleware(PrivateAccess, config=auth)
    if auth is not None:
        app.on_page_exception(lambda: ui.label('Something went wrong. Please reload the page.'))
    ui.run(host=host, port=port, title='Long Catch', reload=False, show=False, dark=True)
