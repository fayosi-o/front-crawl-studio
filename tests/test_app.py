"""Page checks with NiceGUI's simulated user: no browser, but real event handlers and client messages."""

import asyncio
import json
import logging

import pytest
from nicegui.client import Client
from nicegui.testing.user_simulation import user_simulation

from long_catch.app import LongCatchPage
from long_catch.model import PRESETS, ViewState, advice, path_length, timeline_boundaries

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def engine_calls(monkeypatch):
    """Record every JavaScript call the page sends to its browser."""
    sent: list[str] = []
    original = Client.run_javascript

    def record(self, code, **kwargs):
        sent.append(code)
        return original(self, code, **kwargs)

    monkeypatch.setattr(Client, 'run_javascript', record)
    return sent


async def studio() -> None:
    page = LongCatchPage()
    page.build()
    await page.start()


def sent_params(calls: list[str], method: str) -> list[dict]:
    """Arguments of each ``window.LongCatch.<method>(...)`` call, in order."""
    prefix = f'window.LongCatch.{method}('
    return [json.loads(code.split(prefix, 1)[1][:-1]) for code in calls if prefix in code]


async def test_apply_sends_the_suggested_stroke_to_the_swimmer(engine_calls, caplog):
    # Apply rebuilds the Fix first list, deleting the very button that was clicked; the update
    # must still reach the browser engine.
    async with user_simulation(studio) as user:
        await user.open('/')
        for _ in range(100):
            if any('window.LongCatch.start(' in code for code in engine_calls):
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail('The engine never started.')

        with caplog.at_level(logging.ERROR):
            user.find('Apply').click()  # the top suggestion
            await asyncio.sleep(0.05)

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    expected = json.loads(json.dumps(advice(ViewState())[0].apply(ViewState()).render_params()))
    assert sent_params(engine_calls, 'set')[-1:] == [expected]


def recovery_start(user) -> float:
    """Where the recovery segment starts on the studio timeline, as a fraction of the cycle."""
    (segment,) = user.find(marker=None, content='Recovery').elements
    return float(segment.parent_slot.parent._style['left'].rstrip('%')) / 100


async def test_timeline_shows_the_felt_load_slowing_the_pull(engine_calls):
    async with user_simulation(studio) as user:
        await user.open('/')
        view = ViewState()
        length = path_length(view.settings.rate)
        heavy = timeline_boundaries(length, feel=view.render_params()['feel'])
        assert recovery_start(user) == pytest.approx(heavy[-1], abs=1e-4)
        assert heavy[-1] > timeline_boundaries(length)[-1]

        user.find('Short slipping').click()  # a light, slipping hand: an earlier exit
        slipping = ViewState(settings=PRESETS['Short slipping'])
        light = timeline_boundaries(path_length(slipping.settings.rate), feel=slipping.render_params()['feel'])
        assert recovery_start(user) == pytest.approx(light[-1], abs=1e-4)
