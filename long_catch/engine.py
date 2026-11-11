"""Python handle for the browser-side animation engine in ``static/engine.js``."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from nicegui import ui

from long_catch.model import PHASE_LABELS
from long_catch.swimmer import BODY, SceneIds
from long_catch.theme import PALETTE, STATIC_DIR


@cache
def engine_script() -> str:
    """Inline <script>: engine configuration followed by the engine source."""
    config = {
        'colors': {'hold': PALETTE.hold, 'slip': PALETTE.slip, 'skin': PALETTE.skin},
        'phases': list(PHASE_LABELS.values()),
        'arm': [BODY.upper_arm, BODY.forearm],
    }
    source = (STATIC_DIR / 'engine.js').read_text(encoding='utf-8')
    return f'<script>window.LONG_CATCH_CONFIG = {json.dumps(config)};\n{source}</script>'


class BrowserEngine:
    """Sends commands to ``window.LongCatch`` for one connected client."""

    def __init__(self) -> None:
        self.started = False

    def start(self, scene_id: int, ids: SceneIds, params: dict[str, Any]) -> None:
        self._call('start', scene_id, ids, params)
        self.started = True

    def set(self, params: dict[str, Any]) -> None:
        if self.started:
            self._call('set', params)

    def step(self, amount: float) -> None:
        self._call('step', amount)

    def reset_camera(self) -> None:
        self._call('resetCamera')

    @staticmethod
    def _call(method: str, *args: Any) -> None:
        arguments = ', '.join(json.dumps(arg) for arg in args)
        ui.run_javascript(f'window.LongCatch && window.LongCatch.{method}({arguments})')
