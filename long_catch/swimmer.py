"""Procedural swimmer, water, and lane ropes built from basic NiceGUI scene primitives.

Coordinates: head towards +x, z up, right side towards -y, water surface at z=0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nicegui import ui

from long_catch.theme import PALETTE, Palette

SceneIds = dict[str, int | list[int]]
SIDES = (('R', -1), ('L', 1))


@dataclass(frozen=True, slots=True)
class BodyDimensions:
    upper_arm: float = 0.28
    forearm: float = 0.27
    thigh: float = 0.38
    shin: float = 0.36
    shoulder_y: float = 0.235
    hip_y: float = 0.09


BODY = BodyDimensions()


def limb_x(length: float, root_radius: float, tip_radius: float, color: str, direction: int = 1):
    """Tapered segment ending exactly at its joint pivots, along local +/-x."""
    return (
        ui.scene.cylinder(tip_radius, root_radius, length, 20)
        .material(color)
        .rotate(0, 0, -direction * math.pi / 2)
        .move(direction * length / 2, 0, 0)
    )


def ellipsoid(sx: float, sy: float, sz: float, color: str, opacity: float = 1.0):
    return ui.scene.sphere(1, 20, 12).material(color, opacity).scale(sx, sy, sz)


class SwimmerBuilder:
    """Builds the scene inside an active ``ui.scene`` context and records animated object ids."""

    def __init__(self, body: BodyDimensions = BODY, palette: Palette = PALETTE) -> None:
        self.body = body
        self.colors = palette
        self.ids: SceneIds = {}

    def build(self) -> SceneIds:
        self._water()
        with ui.scene.group().move(0, 0, -0.06):
            with self._register('chest', ui.scene.group()):
                self._torso()
                self._head()
                for side, sign in SIDES:
                    self._arm(side, sign)
            with self._register('pelvis', ui.scene.group().move(-0.36, 0, 0)):
                self._pelvis()
                for side, sign in SIDES:
                    self._leg(side, sign)
        self._lane_ropes()
        return self.ids

    def _register(self, name: str, obj):
        self.ids[name] = obj.id
        return obj

    def _patch(self, name: str, obj):
        """Amber emphasis overlay, invisible until the engine sets its opacity."""
        return self._register(name, obj.material(self.colors.patch, 0.0))

    def _water(self) -> None:
        self._register('water', ui.scene.plane(10, 4).material(self.colors.water, 0.16, 'both').move(-0.5, 0, 0.0))

    def _torso(self) -> None:
        skin = self.colors.skin
        ui.scene.cylinder(0.20, 0.125, 0.55, 32).material(skin).rotate(0, 0, -math.pi / 2).scale(1, 1, 0.62).move(
            -0.025, 0, 0
        )
        ui.scene.sphere(1, 24, 16).material(skin).scale(0.09, 0.20, 0.12).move(0.20, 0, 0)
        ui.scene.sphere(1, 24, 16).material(skin).scale(0.21, 0.135, 0.095).move(-0.27, 0, 0)
        for side, sign in SIDES:
            self._patch('back' + side, ellipsoid(0.18, 0.055, 0.03, self.colors.patch)).move(0.01, sign * 0.12, 0.10)

    def _head(self) -> None:
        skin = self.colors.skin
        with ui.scene.group().move(0.29, 0, 0):
            limb_x(0.11, 0.052, 0.045, skin)
        ui.scene.sphere(0.11, 24, 16).material(skin).scale(1.25, 0.85, 1.03).move(0.50, 0, 0.015)
        ui.scene.sphere(0.112, 24, 16).material(self.colors.suit).scale(1.02, 0.87, 0.94).move(0.47, 0, 0.055)
        ui.scene.sphere(0.028, 16, 10).material(skin).scale(1.2, 0.7, 0.7).move(0.56, 0, -0.08)
        for y in (-0.052, 0.052):
            ui.scene.sphere(0.032, 16, 10).material(self.colors.goggles).scale(0.9, 1, 0.4).move(0.54, y, -0.082)

    def _arm(self, side: str, sign: int) -> None:
        skin, b = self.colors.skin, self.body
        with self._register('sh' + side, ui.scene.group().move(0.27, sign * b.shoulder_y, 0)):
            ui.scene.sphere(0.065, 20, 14).material(skin)
            limb_x(b.upper_arm, 0.058, 0.041, skin)
            self._patch('tri' + side, ellipsoid(0.095, 0.038, 0.025, self.colors.patch)).move(0.13, 0, 0.035)
            with self._register('el' + side, ui.scene.group().move(b.upper_arm, 0, 0)):
                ui.scene.sphere(0.042, 18, 12).material(skin)
                self._register('fa' + side, limb_x(b.forearm, 0.042, 0.028, skin))
                with self._register('wr' + side, ui.scene.group().move(b.forearm, 0, 0)):
                    ui.scene.sphere(0.029, 16, 10).material(skin)
                    self._register('ha' + side, ellipsoid(0.08, 0.046, 0.018, skin)).move(0.065, 0, 0)
                    # Thumbs sit on the inner edge of each palm.
                    thumb = ui.scene.sphere(0.028, 16, 10).material(skin)
                    self._register('thumb' + side, thumb).scale(1.1, 0.6, 0.65).move(0.026, -sign * 0.045, -0.005)

    def _pelvis(self) -> None:
        ellipsoid(0.16, 0.165, 0.12, self.colors.suit).move(-0.02, 0, 0)
        self._patch('core', ellipsoid(0.10, 0.13, 0.105, self.colors.patch)).move(0.13, 0, 0.015)
        for side, sign in SIDES:
            hip = ui.scene.sphere(0.065, 16, 10).material(self.colors.patch, 0.0)
            self._patch('hip' + side, hip).scale(1.3, 0.5, 0.8).move(-0.02, sign * 0.15, 0.025)

    def _leg(self, side: str, sign: int) -> None:
        skin, b = self.colors.skin, self.body
        with self._register('leg' + side, ui.scene.group().move(-0.08, sign * b.hip_y, 0)):
            ui.scene.sphere(0.073, 20, 14).material(self.colors.suit)
            limb_x(b.thigh, 0.072, 0.045, skin, direction=-1)
            with self._register('knee' + side, ui.scene.group().move(-b.thigh, 0, 0)):
                ui.scene.sphere(0.046, 18, 12).material(skin)
                limb_x(b.shin, 0.046, 0.026, skin, direction=-1)
                ellipsoid(0.13, 0.043, 0.044, skin).move(-0.13, 0, 0)
                with self._register('ankle' + side, ui.scene.group().move(-b.shin, 0, 0)):
                    ui.scene.sphere(0.028, 16, 10).material(skin)
                    ellipsoid(0.115, 0.043, 0.026, skin).move(-0.075, 0, -0.01)

    def _lane_ropes(self) -> None:
        # The near (right, -y) rope sits lower so it frames rather than hides the swimmer.
        buoys = []
        for y, z in ((1.2, 0.02), (-1.2, -0.01)):
            for i in range(18):
                color = self.colors.hold if i % 2 else self.colors.text
                buoys.append(ui.scene.sphere(0.045, 12, 8).material(color).move(-4.25 + i * 0.5, y, z).id)
        self.ids['buoys'] = buoys
