from pyproj import Transformer


class GeoTransformer:
    """
    Converts GPS coordinates (degrees) to metric coordinates (meters) and back.

    WHY: GPS coordinates are in degrees (longitude/latitude). Degrees are not
    a uniform unit of distance — 1 degree of longitude near the equator is
    ~111 km, but near the poles it shrinks to nearly 0. For algorithms like
    KDTree that compute Euclidean distances, we need coordinates in meters
    so that distances are accurate and comparable.

    We use:
      - EPSG:4326 — the standard GPS coordinate system (degrees)
      - EPSG:2178 — Poland CS2000 zone 7, a projected metric system for Poland (meters)
    """

    def __init__(self):
        # Transformer from GPS degrees to metric meters (Poland CS2000 zone 7)
        self._to_meters = Transformer.from_crs("EPSG:4326", "EPSG:2178", always_xy=True)
        # Transformer back from metric meters to GPS degrees
        self._to_degrees = Transformer.from_crs("EPSG:2178", "EPSG:4326", always_xy=True)

    def to_meters(self, lon: float, lat: float) -> tuple[float, float]:
        """
        Convert GPS coordinates (lon, lat) in degrees to metric (x, y) in meters.
        Returns (x_meters, y_meters) in EPSG:2178.
        """
        x, y = self._to_meters.transform(lon, lat)
        return x, y

    def to_degrees(self, x: float, y: float) -> tuple[float, float]:
        """
        Convert metric (x, y) in meters back to GPS (lon, lat) in degrees.
        Returns (lon, lat) in EPSG:4326.
        """
        lon, lat = self._to_degrees.transform(x, y)
        return lon, lat