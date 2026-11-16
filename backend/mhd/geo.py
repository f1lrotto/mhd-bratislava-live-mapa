"""Small planar geometry helpers in a local metric projection around Bratislava."""

from __future__ import annotations

import math

LAT0 = 48.15
KX = 111_320.0 * math.cos(math.radians(LAT0))  # metres per degree of longitude
KY = 110_574.0  # metres per degree of latitude


def to_xy(lon: float, lat: float) -> tuple[float, float]:
    return lon * KX, lat * KY


def to_lonlat(x: float, y: float) -> tuple[float, float]:
    return x / KX, y / KY


def project_on_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> tuple[float, float, float, float]:
    """Return (t, distance, qx, qy): t in [0, 1] along a→b, distance from p to the closest point q."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    qx, qy = ax + t * dx, ay + t * dy
    return t, math.hypot(px - qx, py - qy), qx, qy


class Polyline:
    """A line with cumulative distances, for projecting points onto it."""

    def __init__(self, coords_lonlat: list[tuple[float, float]]):
        self.xy = [to_xy(lon, lat) for lon, lat in coords_lonlat]
        self.cum = [0.0]
        for (ax, ay), (bx, by) in zip(self.xy, self.xy[1:]):
            self.cum.append(self.cum[-1] + math.hypot(bx - ax, by - ay))
        self.length = self.cum[-1]

    def project(
        self, lon: float, lat: float, lo: float = 0.0, hi: float = math.inf
    ) -> tuple[float, float]:
        """Distance along the line of the closest point, and the distance to it.

        Only segments overlapping [lo, hi] (distance along the line) are considered."""
        px, py = to_xy(lon, lat)
        best = (0.0, math.inf)
        for i in range(len(self.xy) - 1):
            if self.cum[i + 1] < lo or self.cum[i] > hi:
                continue
            (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
            t, d, _, _ = project_on_segment(px, py, ax, ay, bx, by)
            if d < best[1]:
                best = (self.cum[i] + t * (self.cum[i + 1] - self.cum[i]), d)
        return best

    def bearing_at(self, along: float) -> int | None:
        for i in range(len(self.xy) - 1):
            if self.cum[i + 1] >= along and self.cum[i + 1] > self.cum[i]:
                (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
                return int(round(math.degrees(math.atan2(bx - ax, by - ay)))) % 360
        return None
