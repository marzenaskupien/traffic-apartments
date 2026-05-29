# Kraków Apartment Traffic Analyzer

A beginner-friendly local MVP that lets you explore apartments in Kraków,
draw a polygon on an interactive map, and instantly see which apartments
fall inside the selected area together with their nearby traffic scores.

Everything runs locally using CSV files — no API, no database, no Docker required.

---

## How to run

### macOS / Linux

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Windows

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501 in your browser.

---

## Project structure

```
traffic_apartments/
│
├── app.py                    ← Streamlit application entry point
├── requirements.txt
├── README.md
│
├── data/
│   ├── apartments.csv        ← 24 sample Kraków apartments
│   └── traffic_points.csv    ← 17 traffic measurement points
│
└── src/
    ├── geo/
    │   ├── __init__.py
    │   ├── transformer.py    ← Coordinate transformation (EPSG:4326 ↔ EPSG:2178)
    │   ├── spatial_search.py ← KDTree prefilter + Shapely point-in-polygon
    │   └── geometry_utils.py ← Polygon extraction + ConvexHull helper
    │
    ├── traffic/
    │   ├── __init__.py
    │   └── traffic_score.py  ← KDTree radius search + inverse-distance weighting
    │
    └── apartments/
        ├── __init__.py
        └── loader.py         ← CSV loading + price_per_m2 enrichment
```

---

## CSV files

### data/apartments.csv

Columns: `id, title, district, price, area, rooms, lat, lon, url`

Contains 24 sample apartments across Kraków districts:
Krowodrza, Grzegórzki, Podgórze, Kazimierz, Nowa Huta, Bronowice, Dębniki, Prądnik Czerwony.

### data/traffic_points.csv

Columns: `id, name, lat, lon, traffic_level`

Contains 17 traffic measurement points at major Kraków intersections and streets.
`traffic_level` is a value from 0 (no traffic) to 100 (heavy traffic).

---

## Computational geometry concepts used

### 1. Coordinate transformation — `src/geo/transformer.py`

**Why:** GPS coordinates are in degrees (EPSG:4326). Degrees are not a uniform
unit of distance — 1° of longitude varies from ~111 km at the equator to 0 km
at the poles. KDTree and ConvexHull need Euclidean distances, which only make
sense in a metric coordinate system.

**Solution:** `GeoTransformer` uses `pyproj` to project coordinates to
Poland CS2000 Zone 7 (EPSG:2178), where the unit is meters.

All apartment, traffic point, and polygon coordinates are transformed before
any spatial computation.

### 2. KDTree as a practical spatial search structure — two uses

**What is a KDTree?**
A KDTree is a binary tree that partitions points in space so you can quickly
answer questions like "which points are within distance R of this location?"
without checking every single point. This is the practical equivalent of the
Range Tree / spatial range search concept from computational geometry.

#### A. Apartment polygon prefilter — `src/geo/spatial_search.py`

When the user draws a polygon, we do not immediately check every apartment
with Shapely (which would be O(n) per query). Instead:

1. Transform polygon vertices to meters.
2. Build a Shapely Polygon.
3. Compute the bounding box of the polygon.
4. Compute the bounding-box center and a search radius = half the diagonal.
5. Call `KDTree.query_ball_point(center, radius)` → fast candidate list.
6. Run the exact Shapely test only on this small candidate set.

This is inspired by the Range Tree / spatial range search idea: use a fast
approximate filter first, then apply the exact but slower test to few candidates.

#### B. Traffic score — `src/traffic/traffic_score.py`

For each apartment, `KDTree.query_ball_point(apartment_position, radius_meters)`
finds all traffic measurement points within the selected radius. Then the
traffic score is computed as an inverse-distance weighted average of their
`traffic_level` values.

### 3. Point-in-polygon testing — `src/geo/spatial_search.py`

**Algorithm:** Shapely's `polygon.covers(point)`.

`covers()` is preferred over `contains()` because `covers()` also returns
`True` for points that lie exactly on the polygon boundary (edge or vertex),
while `contains()` would exclude those boundary points.

### 4. Traffic score with inverse-distance weighting — `src/traffic/traffic_score.py`

For each nearby traffic measurement point found by the KDTree:

```
weight = 1 / (distance + 1)
traffic_score = Σ(weight × traffic_level) / Σ(weight)
```

The `+1` avoids division by zero when a traffic point is exactly at the
apartment location. Closer points contribute more to the score.

If no traffic points are found within the radius, the score is `0.0`.

### 5. Optional convex hull — `src/geo/geometry_utils.py`

**What is a convex hull?**
The convex hull is the smallest convex polygon that contains all given points.
Visually, imagine stretching a rubber band around the outermost points and
letting it snap — the resulting shape is the convex hull.

**Implementation:** `scipy.spatial.ConvexHull` (uses the Quickhull algorithm).

When enabled in the sidebar and at least 3 apartments are selected, the app:
1. Converts selected apartment positions to metric coordinates.
2. Computes `ConvexHull` in metric space.
3. Converts hull vertices back to GPS degrees.
4. Draws a dashed blue polygon on the Folium map.

---

## Application flow

```
CSV files (apartments.csv, traffic_points.csv)
  → coordinate transformation: GPS degrees → meters (EPSG:4326 → EPSG:2178)
  → KDTree spatial index built (once at startup, for both apartments and traffic points)
  → user draws polygon on the Folium map
  → KDTree prefilter: fast candidate selection using bounding-box center + radius
  → Shapely point-in-polygon test: exact check with polygon.covers(point)
  → traffic score: KDTree radius search + inverse-distance weighted average
  → sidebar filtering: traffic threshold, district multiselect
  → map markers (green / orange / red) + DataFrame table visualization
  → optional: ConvexHull drawn around selected apartments
```

---

## Algorithms and course concepts used

| Concept | Where | How |
|---|---|---|
| **KDTree** (spatial range search, inspired by Range Tree) | `SpatialSearchEngine`, `TrafficScorer` | Candidate prefilter for polygon search; nearby traffic point lookup |
| **Point-in-polygon** | `SpatialSearchEngine.search_inside_polygon` | `polygon.covers(point)` from Shapely |
| **Coordinate transformation** | `GeoTransformer` | `pyproj` EPSG:4326 → EPSG:2178; required for metric distance calculations |
| **Convex hull** | `calculate_convex_hull`, `app.py` | `scipy.spatial.ConvexHull`; optional visualization of the outer boundary |
| **Inverse-distance weighting** | `TrafficScorer.calculate_score_for_point` | `weight = 1 / (distance + 1)` for weighted traffic score |

---

## Marker color legend

- **Green** — traffic score < 35 (low traffic)
- **Orange** — traffic score 35–70 (moderate traffic)
- **Red** — traffic score > 70 (heavy traffic)