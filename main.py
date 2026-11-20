"""Long Catch: a local 3D front-crawl stroke explorer.

Run with ``python main.py``. Locally it picks a free port and prints the address; set
``LONG_CATCH_PORT`` to pin one (the browser checks use 8080).
"""

import os
import random
import socket
from collections.abc import Mapping

from nicegui import app, ui

import long_catch.app  # noqa: F401  (registers the page)
from long_catch.auth import AuthConfig, PrivateAccess

LOCAL_PORTS = range(8100, 8900)  # clear of the usual dev-server ports (3000, 5000, 8000, 8080)


def free_port(host: str = '127.0.0.1') -> int:
    """A random unused port in ``LOCAL_PORTS``, or whatever the OS offers if they are all taken."""
    for port in random.sample(LOCAL_PORTS, 20):
        with socket.socket() as probe:
            if probe.connect_ex((host, port)) != 0:
                return port
    with socket.socket() as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def server_address(environ: Mapping[str, str] = os.environ) -> tuple[str, int]:
    port = environ.get('PORT')
    if port:
        return '0.0.0.0', int(port)
    return '127.0.0.1', int(environ.get('LONG_CATCH_PORT') or free_port())


if __name__ in {'__main__', '__mp_main__'}:
    host, port = server_address()
    auth = AuthConfig.from_env()
    app.add_middleware(PrivateAccess, config=auth)
    if auth is not None:
        app.on_page_exception(lambda: ui.label('Something went wrong. Please reload the page.'))
    ui.run(host=host, port=port, title='Long Catch', reload=False, show=False, dark=True)
