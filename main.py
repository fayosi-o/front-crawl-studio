"""Long Catch: a local 3D front-crawl stroke explorer.

Run with ``python main.py`` and open http://127.0.0.1:8080.
"""

from nicegui import ui

import long_catch.app  # noqa: F401  (registers the page)

if __name__ in {'__main__', '__mp_main__'}:
    ui.run(host='127.0.0.1', port=8080, title='Long Catch', reload=False, show=False, dark=True)
