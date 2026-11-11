"""Long Catch: a silent visual prototype of front-crawl stroke shape.

Run with ``python main.py`` and open http://127.0.0.1:8080.
All numbers and muscle colours are coaching estimates, not measured data.
"""

from nicegui import ui

import long_catch.app  # noqa: F401  (registers the page)

if __name__ in {'__main__', '__mp_main__'}:
    ui.run(host='127.0.0.1', port=8080, title='Long Catch', reload=False, show=False, dark=True)
