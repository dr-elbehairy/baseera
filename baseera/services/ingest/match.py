"""Asset matching: by normalised code first, then spatially within the configured radius (default 25 m)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.geo import bbox, haversine_m
from ...core.models import Asset
from .base import RowError, normalise_code


class AssetMatcher:
    def __init__(self, db: Session):
        self.db = db
        self.radius = get_settings().match_radius_m
        self._by_code: dict[str, Asset] | None = None

    def _index(self) -> dict[str, Asset]:
        if self._by_code is None:
            self._by_code = {a.asset_code: a for a in self.db.query(Asset).filter(Asset.active.is_(True)).all()}
        return self._by_code

    def invalidate(self) -> None:
        self._by_code = None

    def by_code(self, code: str) -> Asset | None:
        return self._index().get(normalise_code(code))

    def nearest(self, lon: float, lat: float) -> tuple[Asset | None, float]:
        x0, y0, x1, y1 = bbox(lon, lat, self.radius)
        cands = (self.db.query(Asset).filter(Asset.active.is_(True), Asset.lon.between(x0, x1), Asset.lat.between(y0, y1)).all())
        best, bd = None, float("inf")
        for a in cands:
            d = haversine_m(lon, lat, a.lon, a.lat)
            if d < bd:
                best, bd = a, d
        if best is None or bd > self.radius:
            return None, bd
        return best, bd

    def resolve(self, code: str | None, lon: float | None, lat: float | None) -> tuple[Asset, str]:
        """Returns (asset, method). Raises RowError with a precise reason when nothing matches."""
        if code:
            a = self.by_code(code)
            if a:
                return a, "code"
            if lon is None or lat is None:
                raise RowError(f"unknown asset code {normalise_code(code)!r} and no coordinates to match spatially")
        if lon is not None and lat is not None:
            a, d = self.nearest(float(lon), float(lat))
            if a:
                return a, "spatial"
            near = f"; nearest {d:.0f} m" if d != float("inf") else ""
            raise RowError(f"no asset within {self.radius:.0f} m of ({lon}, {lat}){near}")
        raise RowError("row has neither asset code nor coordinates")
