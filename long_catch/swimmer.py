"""Procedural swimmer, water, and lane ropes built from basic NiceGUI scene primitives.

Coordinates: head towards +x, z up, right side towards -y, water surface at z=0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nicegui import ui

from long_catch.theme import PALETTE, Palette

SceneIds = dict[str, int | list[int]]  # object name -> scene id(s) the engine animates
SIDES = (('R', -1), ('L', 1))  # id suffix and y sign for each body side


@dataclass(frozen=True, slots=True)
class BodyDimensions:
    """Limb lengths and joint offsets in metres. The engine's IK reads the arm lengths."""

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
    """Unit sphere scaled to the given semi-axes."""
    return ui.scene.sphere(1, 20, 12).material(color, opacity).scale(sx, sy, sz)


# ---- head geometry (chest frame, metres) ----------------------------------------------------
Vec = tuple[float, float, float]
HEAD_CENTRE: Vec = (0.50, 0.0, 0.015)
HEAD_AXES: Vec = (0.1375, 0.0935, 0.113)  # skull semi-axes: crown (+x), side (y), back of head (+z)
EYE_DIR: Vec = (0.04, 0.052, -0.097)  # right/left eye offset from the head centre (y sign flipped per side)


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scaled(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Vec) -> Vec:
    return _scaled(a, 1 / math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2))


def head_surface(dx: float, dy: float, dz: float) -> tuple[Vec, Vec]:
    """Point on the skull in direction (dx, dy, dz) from its centre, and the outward normal there."""
    u = _unit((dx / HEAD_AXES[0], dy / HEAD_AXES[1], dz / HEAD_AXES[2]))
    point = _add(HEAD_CENTRE, (u[0] * HEAD_AXES[0], u[1] * HEAD_AXES[1], u[2] * HEAD_AXES[2]))
    normal = _unit((u[0] / HEAD_AXES[0], u[1] / HEAD_AXES[1], u[2] / HEAD_AXES[2]))
    return point, normal


def basis(x_axis: Vec, y_axis: Vec) -> list[list[float]]:
    """Rotation matrix (rows) whose columns turn local x, y, z onto the given orthonormal axes."""
    z_axis = _cross(x_axis, y_axis)
    return [[x_axis[i], y_axis[i], z_axis[i]] for i in range(3)]


class SwimmerBuilder:
    """Builds the scene inside an active ``ui.scene`` context and records animated object ids."""

    def __init__(self, body: BodyDimensions = BODY, palette: Palette = PALETTE) -> None:
        self.body = body
        self.colors = palette
        self.ids: SceneIds = {}

    def build(self) -> SceneIds:
        """Create the water, swimmer, and lane ropes; return the ids the engine needs.

        The chest and pelvis are separate groups so the engine can roll them
        independently (flat hips, snaking, sinking legs).
        """
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
        """Record ``obj``'s id under ``name`` for the engine and return it for chaining."""
        self.ids[name] = obj.id
        return obj

    def _patch(self, name: str, obj):
        """Amber emphasis overlay, invisible until the engine sets its opacity."""
        return self._register(name, obj.material(self.colors.patch, 0.0))

    def _water(self) -> None:
        """Double-sided surface plane at z = 0; the engine adds waves and the pool floor."""
        self._register('water', ui.scene.plane(10, 4).material(self.colors.water, 0.16, 'both').move(-0.5, 0, 0.0))

    def _torso(self) -> None:
        """Tapered trunk, chest and waist volumes, and the two back-muscle patches."""
        skin = self.colors.skin
        trunk = ui.scene.cylinder(0.20, 0.125, 0.55, 32).material(skin)
        trunk.rotate(0, 0, -math.pi / 2).scale(1, 1, 0.62).move(-0.025, 0, 0)
        ui.scene.sphere(1, 24, 16).material(skin).scale(0.09, 0.20, 0.12).move(0.20, 0, 0)
        ui.scene.sphere(1, 24, 16).material(skin).scale(0.21, 0.135, 0.095).move(-0.27, 0, 0)
        for side, sign in SIDES:
            self._patch('back' + side, ellipsoid(0.18, 0.055, 0.03, self.colors.patch)).move(0.01, sign * 0.12, 0.10)

    def _head(self) -> None:
        """Neck, head, jaw, nose, swim cap, and goggles; the face points down (-z).

        The skull and cap are built on a unit sphere inside one scaled group,
        so the cap dome hugs the head exactly. The goggles are placed in the
        chest frame, aimed along the skull's surface normal, so the lenses
        are not stretched by that scale.
        """
        c = self.colors
        with ui.scene.group().move(0.29, 0, 0):
            limb_x(0.11, 0.052, 0.045, c.skin)
        centre, axes = HEAD_CENTRE, HEAD_AXES
        # Chin and nose: in swim pose "down and forward" maps to -x and -z.
        ellipsoid(0.07, 0.068, 0.05, c.skin).move(centre[0] - 0.035, 0, centre[2] - 0.065)
        ui.scene.sphere(0.026, 16, 10).material(c.skin).scale(1.25, 0.7, 0.75).move(0.565, 0, -0.085)
        with ui.scene.group().move(*centre).scale(*axes):
            ui.scene.sphere(1, 32, 20).material(c.skin)
            # Cap dome: axis tilted 30 deg from straight up towards the crown, covering ears and nape.
            with ui.scene.group().rotate(0, math.radians(30), 0):
                with ui.scene.group().rotate(math.pi / 2, 0, 0):
                    edge = math.radians(100)
                    profile = [
                        [1.05 * math.sin(t), 1.05 * math.cos(t)] for t in (edge * (1 - i / 14) for i in range(15))
                    ]
                    ui.scene.lathe(profile, 40).material(c.cap, 1.0, 'both')
                    rim = ui.scene.torus(1.05 * math.sin(edge), 0.035, 10, 64).material(c.cap)
                    rim.rotate(math.pi / 2, 0, 0).move(0, 1.05 * math.cos(edge), 0)
            self._goggle_strap()
        eyes = []
        for sign in (-1, 1):
            point, normal = head_surface(EYE_DIR[0], sign * EYE_DIR[1], EYE_DIR[2])
            eyes.append((point, normal))
            across = _unit(_sub((0.0, 1.0, 0.0), _scaled(normal, normal[1])))
            with ui.scene.group().move(*point).rotate_R(basis(across, normal)):
                ui.scene.cylinder(0.025, 0.028, 0.016, 24).material(c.rubber).scale(1.3, 1, 1).move(0, 0.004, 0)
                ui.scene.torus(0.026, 0.0045, 8, 32).material(c.rubber).rotate(math.pi / 2, 0, 0).scale(1.3, 1, 1).move(
                    0, 0.012, 0
                )
                ellipsoid(0.031, 0.008, 0.023, c.lens).move(0, 0.012, 0)
        # Nose bridge between the two eye cups, standing just off the face.
        (p_r, n_r), (p_l, _) = eyes
        gap = p_l[1] - p_r[1] - 2 * 0.03
        mid = _add(_scaled(_add(p_r, p_l), 0.5), _scaled(n_r, 0.012))
        ui.scene.cylinder(0.0035, 0.0035, gap, 8).material(c.rubber).move(mid[0], 0, mid[2])

    def _goggle_strap(self) -> None:
        """Strap arc (unit-head space) from one goggle's outer edge round the back of the cap to the other."""
        u_eye = _unit((EYE_DIR[0] / HEAD_AXES[0], EYE_DIR[1] / HEAD_AXES[1], EYE_DIR[2] / HEAD_AXES[2]))
        u_back = _unit((-0.3, 0.0, 0.95))
        # Plane through both eyes and the back of the head; symmetric, so its normal lies in x-z.
        dx, dz = u_eye[0] - u_back[0], u_eye[2] - u_back[2]
        normal = _unit((-dz, 0.0, dx))
        if normal[0] < 0:
            normal = _scaled(normal, -1)
        offset = sum(a * n for a, n in zip(u_back, normal, strict=True))
        x0 = _unit(_sub(u_back, _scaled(normal, offset)))
        y0 = _cross(normal, x0)
        v = _sub(u_eye, _scaled(normal, offset))
        half = abs(
            math.atan2(sum(a * b for a, b in zip(v, y0, strict=True)), sum(a * b for a, b in zip(v, x0, strict=True)))
        )
        half -= 0.32  # stop at the goggle's outer edge, not its centre
        start = _add(_scaled(x0, math.cos(-half)), _scaled(y0, math.sin(-half)))
        radius = 1.075 * math.sqrt(max(0.0, 1 - offset**2))
        strap = ui.scene.torus(radius, 0.04, 8, 64, 2 * half).material(self.colors.rubber)
        strap.rotate_R(basis(start, _cross(normal, start))).move(*_scaled(normal, 1.075 * offset))

    def _arm(self, side: str, sign: int) -> None:
        """Nested shoulder -> elbow -> wrist groups so the engine can pose each joint."""
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
        """Hips in suit colour, plus the core and hip-drive emphasis patches."""
        ellipsoid(0.16, 0.165, 0.12, self.colors.suit).move(-0.02, 0, 0)
        self._patch('core', ellipsoid(0.10, 0.13, 0.105, self.colors.patch)).move(0.13, 0, 0.015)
        for side, sign in SIDES:
            hip = ui.scene.sphere(0.065, 16, 10).material(self.colors.patch, 0.0)
            self._patch('hip' + side, hip).scale(1.3, 0.5, 0.8).move(-0.02, sign * 0.15, 0.025)

    def _leg(self, side: str, sign: int) -> None:
        """Nested hip -> knee -> ankle groups, pointing back (-x) from the pelvis."""
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
        """Two ropes of alternating buoys; the engine scrolls them to suggest forward speed."""
        # The near (right, -y) rope sits lower so it frames rather than hides the swimmer.
        buoys = []
        for y, z in ((1.2, 0.02), (-1.2, -0.01)):
            for i in range(18):
                color = self.colors.hold if i % 2 else self.colors.text
                buoys.append(ui.scene.sphere(0.045, 12, 8).material(color).move(-4.25 + i * 0.5, y, z).id)
        self.ids['buoys'] = buoys
