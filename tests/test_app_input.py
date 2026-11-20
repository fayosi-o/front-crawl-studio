"""Values from the browser are bounded before they reach the model: a client can send anything."""

import asyncio
import logging
import math

import pytest
from nicegui import ui
from nicegui.client import Client
from nicegui.testing.user_simulation import user_simulation

from long_catch.app import LongCatchPage, bounded_number

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (50, 50),
        ('42', 42),
        (41.6, 42),
        (100000, 70),
        (1e308, 70),
        (10**309, None),
        (-5, 30),
        (math.inf, None),
        (math.nan, None),
        ('nan', None),
        ('1e999', None),
        ('lots', None),
        (None, None),
        (True, None),
        ([50], None),
        ({'value': 50}, None),
    ],
)
def test_browser_values_are_bounded_numbers(value, expected):
    result = bounded_number(value, 30, 70)
    assert result == expected and type(result) is type(expected)


def test_bounded_numbers_land_on_the_control_notches():
    assert [bounded_number(v, 2, 6, 2) for v in (1, 3.2, 4.9, 7)] == [2, 4, 4, 6]  # kick beats
    assert [bounded_number(v, 0.5, 5.0, 0.5) for v in (0, 1.6, 2, 99)] == [0.5, 1.5, 2.0, 5.0]  # trail seconds


def send(element: ui.element, raw: str) -> None:
    """Deliver ``update:model-value`` the way the socket does: the argument is JSON text from the client."""
    (listener,) = [item for item in element._event_listeners.values() if item.type.startswith('update:')]
    element.client.handle_event({'id': element.id, 'listener_id': listener.id, 'args': [raw]})


def find(container: ui.element, kind: type, label: str) -> ui.element:
    """The ``kind`` element inside ``container`` whose text or option labels include ``label``."""
    for element in container.descendants():
        if isinstance(element, kind):
            labels = element.options.values() if isinstance(element, ui.toggle) else [element.text]
            if label in labels:
                return element
    raise LookupError(label)


async def test_crafted_socket_values_are_bounded_or_ignored(monkeypatch, caplog):
    pages: list[LongCatchPage] = []
    sent: list[str] = []
    original = Client.run_javascript

    def record(self, code, **kwargs):
        sent.append(code)
        return original(self, code, **kwargs)

    monkeypatch.setattr(Client, 'run_javascript', record)

    async def root() -> None:
        page = LongCatchPage()
        pages.append(page)
        page.build()
        await page.start()

    async with user_simulation(root) as user:
        await user.open('/')
        await asyncio.sleep(0.05)
        (page,) = pages
        with caplog.at_level(logging.ERROR):
            send(page.sliders['rate'], '1e308')  # clamped to the top of the range
            for raw in ('"lots"', 'null', '[50]', 'true', '"1e999"'):
                send(page.sliders['rate'], raw)  # not a number: ignored
            send(page.sliders['catch'], '-5')
            send(page.sliders['beats'], '3.2')  # between notches
            send(page.trail_slider, '"nan"')
            send(page.trail_slider, '99')
            send(find(page.studio, ui.switch, 'Water pressure'), '[1, 2, 3]')
            page.switch_mode('race')
            race = page.race
            assert race is not None
            for label in ('25 m', 'Solo', 'Swimmer A', '4x'):
                send(find(page.race_space, ui.toggle, label), 'null')
            send(race.sliders['rate'], '-1e308')
            race.copy_lane()  # the race still works afterwards

    assert not [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    s = page.view.settings
    assert (s.rate, s.catch, s.beats, page.slider_values['rate'].text) == (72, 0, 4, '72 spm')
    assert (page.view.trail_seconds, page.view.pressure) == (5.0, False)
    assert (race.distance, race.count, race.selected) == (50, 2, 0)
    assert race.swimmers[0].settings.rate == race.swimmers[1].settings.rate == 22
    assert not [code for code in sent if 'setSpeed(null)' in code]
