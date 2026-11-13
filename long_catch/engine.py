"""Python handle for the browser-side animation engine in ``static/engine.js``."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from nicegui import ui

from long_catch.model import FINISH_START, PHASE_LABELS, PULL_START, PUSH_START
from long_catch.swimmer import BODY, SceneIds
from long_catch.theme import PALETTE, STATIC_DIR


@cache
def engine_script() -> str:
    """Inline <script>: engine configuration followed by the engine source."""
    config = {
        'colors': {
            'hold': PALETTE.hold,
            'slip': PALETTE.slip,
            'skin': PALETTE.skin,
            'water': PALETTE.water,
            'floor': PALETTE.floor,
        },
        'background': PALETTE.background,
        'phases': list(PHASE_LABELS.values()),
        'finish': FINISH_START,
        'pull': PULL_START,
        'push': PUSH_START,
        'arm': [BODY.upper_arm, BODY.forearm],
    }
    source = (STATIC_DIR / 'engine.js').read_text(encoding='utf-8')
    race = (STATIC_DIR / 'race.js').read_text(encoding='utf-8')
    return f'<script>window.LONG_CATCH_CONFIG = {json.dumps(config)};\n{source}\n{race}</script>'


class BrowserEngine:
    """Sends commands to ``window.LongCatch`` for one connected client."""

    def __init__(self) -> None:
        self.started = False

    def start(self, scene_id: int, ids: SceneIds, params: dict[str, Any]) -> None:
        """Attach the engine to the scene once its objects exist and begin animating."""
        self._call('start', scene_id, ids, params)
        self.started = True

    def set(self, params: dict[str, Any]) -> None:
        """Push new render parameters; ignored until the engine has started."""
        if self.started:
            self._call('set', params)

    def step(self, amount: float) -> None:
        """Pause and move the arm phase by ``amount`` of a cycle (negative steps back)."""
        self._call('step', amount)

    def reset_camera(self) -> None:
        """Return the main (orbit) camera to its starting position."""
        self._call('resetCamera')

    def fit(self) -> None:
        """Resize the renderers after the stage layout changes (e.g. split view)."""
        if self.started:
            self._call('fit')

    def set_active(self, active: bool) -> None:
        """Suspend the studio clock while another mode is visible."""
        self._call('setActive', active)

    def set_view(self, view_id: int, angle: str) -> None:
        """Point the second (split) view's camera at a named angle."""
        if self.started:
            self._call('setView', view_id, angle)

    @staticmethod
    def _call(method: str, *args: Any) -> None:
        # json.dumps makes every argument a JS literal, so nothing is spliced in raw.
        arguments = ', '.join(json.dumps(arg) for arg in args)
        ui.run_javascript(f'window.LongCatch && window.LongCatch.{method}({arguments})')


class RaceEngine:
    """Commands for the separate race clock; no browser state is sent to Python."""

    def __init__(self) -> None:
        self.started = False

    def start(self, scenes: list[dict[str, Any]], config: dict) -> None:
        self.call('start', scenes, config)
        self.started = True

    def set(self, config: dict) -> None:
        if self.started:
            self.call('set', config)

    @staticmethod
    def call(method: str, *args: Any) -> None:
        arguments = ', '.join(json.dumps(arg) for arg in args)
        ui.run_javascript(f'window.LongCatchRace.{method}({arguments})')
