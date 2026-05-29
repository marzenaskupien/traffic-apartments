import math
import numpy as np
import pandas as pd
from scipy.spatial import KDTree
from shapely.geometry import Point, Polygon


class SpatialSearchEngine:
    """
    Finds apartments that lie inside a polygon drawn by the user on the map.

    Algorithm used:
      1. Coordinate transformation — all coordinates are converted to meters (EPSG:2178)
         so that Euclidean distances in the KDTree are accurate.
      2. KDTree prefilter — instead of testing every apartment with Shapely right away,
         we first do a fast radius query around the polygon's bounding-box center.
         This is inspired by Range Tree / spatial range search ideas: narrow down
         candidates quickly, then apply the exact test on the small candidate set.
      3. Shapely point-in-polygon — for each candidate we call polygon.covers(point),
         which handles points exactly on the polygon boundary correctly
         (unlike contains(), which excludes boundary points).
    """

    def __init__(self, dataframe: pd.DataFrame, transformer):
        """
        Parameters
        ----------
        dataframe   : apartments DataFrame, must have 'lon' and 'lat' columns
        transformer : GeoTransformer instance
        """
        self.df = dataframe.reset_index(drop=True)
        self.transformer = transformer

        # Convert every apartment's (lon, lat) to metric (x, y)
        # This is done once at startup so the KDTree build is fast.
        xy = [
            transformer.to_meters(row.lon, row.lat)
            for row in self.df.itertuples()
        ]
        self._xy = np.array(xy)           # shape (n, 2)

        # KDTree: a binary spatial index built on metric coordinates.
        # Inspired by Range Tree / spatial search from computational geometry.
        # query_ball_point(center, r) returns all points within radius r in O(log n + k).
        self._tree = KDTree(self._xy)

    def search_inside_polygon(self, poly_degrees_coords: list) -> pd.DataFrame:
        """
        Return the subset of apartments that lie inside the drawn polygon.

        Parameters
        ----------
        poly_degrees_coords : list of [lon, lat] pairs in GPS degrees
                              (as returned by Folium Draw)

        Steps:
          1. Transform polygon vertices from degrees to meters.
          2. Build a Shapely Polygon from the metric vertices.
          3. Compute bounding box of the polygon.
          4. Compute bounding-box center and the search radius
             (half of the bounding-box diagonal).
          5. Use KDTree.query_ball_point to get candidate apartments
             near the bounding-box center (fast prefilter).
          6. For each candidate, use Shapely polygon.covers(point)
             to do the exact point-in-polygon test.
        """
        if len(poly_degrees_coords) < 3:
            return pd.DataFrame()

        # Step 1 — transform polygon vertices to meters
        poly_meters = [
            self.transformer.to_meters(lon, lat)
            for lon, lat in poly_degrees_coords
        ]

        # Step 2 — build Shapely polygon in metric coordinates
        polygon_shape = Polygon(poly_meters)

        # Step 3 — bounding box of the polygon (in meters)
        min_x, min_y, max_x, max_y = polygon_shape.bounds

        # Step 4 — center and radius for the KDTree prefilter query
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        # Radius = half of the bounding-box diagonal — guarantees all polygon
        # interior points are within this circle of the center.
        diagonal = math.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2)
        radius = diagonal / 2.0 + 1.0   # +1 m safety margin for floating-point edge cases

        # Step 5 — KDTree prefilter: fast candidate selection
        # Returns indices of apartments whose metric position is within `radius` of center.
        # This is a spatial range query — similar in purpose to a Range Tree query.
        candidate_indices = self._tree.query_ball_point([center_x, center_y], radius)

        if not candidate_indices:
            return pd.DataFrame()

        # Step 6 — exact point-in-polygon test with Shapely (covers = includes boundary)
        matching_rows = []
        for idx in candidate_indices:
            x, y = self._xy[idx]
            point = Point(x, y)
            # polygon.covers(point) returns True if point is inside OR on the border
            if polygon_shape.covers(point):
                matching_rows.append(self.df.iloc[idx])

        if not matching_rows:
            return pd.DataFrame()

        return pd.DataFrame(matching_rows).reset_index(drop=True)