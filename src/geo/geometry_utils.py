from scipy.spatial import ConvexHull
import numpy as np


def extract_drawn_polygon(st_data: dict) -> list | None:
    """
    Extract polygon or rectangle coordinates from the streamlit-folium Draw output.

    Folium Draw returns GeoJSON in st_data["last_active_drawing"].
    Both 'polygon' and 'rectangle' types store coordinates as a list of rings:
      [ [[lon, lat], [lon, lat], ...] ]

    Returns a list of [lon, lat] pairs, or None if no valid polygon was drawn.
    """
    if not st_data:
        return None

    drawing = st_data.get("last_active_drawing")
    if not drawing:
        return None

    geometry = drawing.get("geometry", {})
    geo_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geo_type in ("Polygon", "Rectangle") and coords:
        # coords[0] is the outer ring: [[lon, lat], ...]
        # The last point is usually a repeat of the first (closing the ring) — drop it.
        ring = coords[0]
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        # Each element is [lon, lat]
        return [[pt[0], pt[1]] for pt in ring]

    return None


def calculate_convex_hull(points_xy: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """
    Calculate the convex hull of a set of 2D points.

    Convex hull is the smallest convex polygon that contains all given points.
    Visually it looks like a rubber band stretched around the outermost points.

    Uses scipy.spatial.ConvexHull (Quickhull algorithm internally).

    Parameters
    ----------
    points_xy : list of (x, y) tuples — metric coordinates (meters)

    Returns a list of (x, y) tuples representing the hull vertices in order,
    or an empty list if there are fewer than 3 points (a hull needs at least 3).
    """
    if len(points_xy) < 3:
        return []

    pts = np.array(points_xy)
    try:
        hull = ConvexHull(pts)
        # hull.vertices gives indices of hull points in counter-clockwise order
        hull_pts = pts[hull.vertices].tolist()
        return [(p[0], p[1]) for p in hull_pts]
    except Exception:
        # ConvexHull raises if all points are collinear
        return []