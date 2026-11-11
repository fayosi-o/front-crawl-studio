"""Colour palette and stylesheet shared by the scene, engine, and page."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

STATIC_DIR = Path(__file__).parent / 'static'


@dataclass(frozen=True, slots=True)
class Palette:
    background: str = '#07131a'
    panel: str = '#0e252c'
    card: str = '#133139'
    text: str = '#e7f0ea'
    muted: str = '#93aaa6'
    hold: str = '#3dbea5'
    slip: str = '#e36b4f'
    skin: str = '#d8bfa3'
    suit: str = '#1f5563'
    patch: str = '#f2c14e'
    water: str = '#2a8fa8'
    goggles: str = '#233c49'

    def css_variables(self) -> str:
        names = (f'  --lc-{name.replace("_", "-")}: {value};' for name, value in asdict(self).items())
        return ':root {\n' + '\n'.join(names) + '\n}\n'


PALETTE = Palette()


@cache
def stylesheet() -> str:
    """Inline <style> block: palette variables followed by the static stylesheet."""
    css = (STATIC_DIR / 'app.css').read_text(encoding='utf-8')
    return f'<style>\n{PALETTE.css_variables()}{css}</style>'
