import numpy as np
import pandas as pd
from scipy.spatial import KDTree


class TrafficScorer:
    """
    Calculates a traffic score for any geographic point.

    Algorithm:
      1. All traffic measurement points are converted to metric coordinates (meters)
         using GeoTransformer, then stored in a KDTree.
      2. For a query point (an apartment), KDTree.query_ball_point finds all traffic
         measurement points within the selected radius (in meters).
      3. The score is a weighted average of their traffic_level values,
         where the weight for each point is:
             weight = 1 / (distance + 1)
         Points that are closer have higher weight (inverse-distance weighting).
         The +1 avoids division by zero when a point is exactly at distance 0.
      4. If no traffic points are found within the radius, the score is 0.0.

    This is the second use of KDTree in the project (the first is in SpatialSearchEngine).
    Here the radius search efficiently narrows down relevant traffic points
    without looping over all of them.
    """

    def __init__(self, traffic_df: pd.DataFrame, transformer):
        """
        Parameters
        ----------
        traffic_df  : DataFrame with columns lat, lon, traffic_level
        transformer : GeoTransformer instance
        """
        self.traffic_df = traffic_df.reset_index(drop=True)
        self.transformer = transformer

        # Convert traffic point coordinates to meters once at startup
        xy = [
            transformer.to_meters(row.lon, row.lat)
            for row in self.traffic_df.itertuples()
        ]
        self._xy = np.array(xy)           # shape (n, 2)
        self._levels = self.traffic_df["traffic_level"].values.astype(float)

        # KDTree for fast radius lookup of nearby traffic points
        self._tree = KDTree(self._xy)

    def calculate_score_for_point(
        self,
        lon: float,
        lat: float,
        radius_meters: float = 1000.0,
    ) -> float:
        """
        Return the traffic score for a single geographic point.

        Parameters
        ----------
        lon           : longitude of the point (GPS degrees)
        lat           : latitude of the point (GPS degrees)
        radius_meters : search radius in meters; only traffic points within
                        this distance are considered

        Returns a float in [0, 100], or 0.0 if no traffic points are nearby.
        """
        # Convert query point to meters
        x, y = self.transformer.to_meters(lon, lat)

        # KDTree radius query: get indices of all traffic points within radius
        indices = self._tree.query_ball_point([x, y], radius_meters)

        if not indices:
            return 0.0

        # Compute distances manually (query_ball_point does not return distances)
        diffs = self._xy[indices] - np.array([x, y])
        distances = np.sqrt((diffs ** 2).sum(axis=1))

        # Inverse-distance weighting: closer points matter more
        weights = 1.0 / (distances + 1.0)
        levels = self._levels[indices]

        weighted_score = float(np.sum(weights * levels) / np.sum(weights))
        return round(weighted_score, 1)