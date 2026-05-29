"""
Kraków Apartment Traffic Analyzer
==================================
A beginner-friendly Streamlit app that lets you draw a polygon on a map
and see which apartments fall inside it, together with their traffic scores.

Project flow:
  CSV files
  → coordinate transformation (GPS degrees → meters, EPSG:4326 → EPSG:2178)
  → KDTree spatial index (built once at startup for apartments and traffic points)
  → user draws polygon on the Folium map
  → KDTree prefilter (fast candidate selection using bounding-box radius)
  → Shapely point-in-polygon test (exact membership check, covers() for boundary safety)
  → traffic score from nearby traffic points (KDTree radius search + inverse-distance weighting)
  → sidebar filtering (traffic threshold, district)
  → map + table visualization
"""

import sys
import os

# Allow imports from the src/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from folium.plugins import Draw

from geo.transformer import GeoTransformer
from geo.spatial_search import SpatialSearchEngine
from geo.geometry_utils import extract_drawn_polygon, calculate_convex_hull
from traffic.traffic_score import TrafficScorer
from apartments.loader import load_apartments, enrich_apartments

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Kraków Apartment Traffic Analyzer",
    page_icon="🏠",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Data loading (cached so it only runs once per session)
# ---------------------------------------------------------------------------
@st.cache_data
def get_data():
    base = os.path.dirname(__file__)
    apts = load_apartments(os.path.join(base, "data", "apartments.csv"))
    apts = enrich_apartments(apts)
    traffic = pd.read_csv(os.path.join(base, "data", "traffic_points.csv"))
    traffic["lat"] = traffic["lat"].astype(float)
    traffic["lon"] = traffic["lon"].astype(float)
    traffic["traffic_level"] = traffic["traffic_level"].astype(float)
    return apts, traffic


apartments_df, traffic_df = get_data()

# ---------------------------------------------------------------------------
# Geometry / scoring objects (cached so KDTree is built only once)
# ---------------------------------------------------------------------------
@st.cache_resource
def build_engines(apts, traffic):
    transformer = GeoTransformer()
    search_engine = SpatialSearchEngine(apts, transformer)
    scorer = TrafficScorer(traffic, transformer)
    return transformer, search_engine, scorer


transformer, search_engine, scorer = build_engines(apartments_df, traffic_df)

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.title("Filtrowanie")

radius_meters = st.sidebar.slider(
    "Promień wyszukiwania ruchu (m)",
    min_value=200,
    max_value=3000,
    value=800,
    step=100,
    help="KDTree szuka punktów pomiarowych ruchu w tej odległości od każdego mieszkania.",
)

max_traffic = st.sidebar.slider(
    "Maksymalny akceptowany wynik ruchu",
    min_value=0,
    max_value=100,
    value=75,
    step=5,
    help="Pokazuj tylko mieszkania z wynikiem ruchu ≤ tej wartości.",
)

all_districts = sorted(apartments_df["district"].unique().tolist())

show_traffic_pts = st.sidebar.checkbox("Pokaż punkty pomiarowe ruchu", value=True)
show_hull = st.sidebar.checkbox("Pokaż wypukłą otoczkę (convex hull) wybranych mieszkań", value=False)

# ---------------------------------------------------------------------------
# Calculate traffic score for every apartment using the selected radius
# ---------------------------------------------------------------------------
apartments_df["traffic_score"] = apartments_df.apply(
    lambda row: scorer.calculate_score_for_point(row["lon"], row["lat"], radius_meters),
    axis=1,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Kraków Apartment Traffic Analyzer")
st.markdown(
    "Narysuj **wielokąt** lub **prostokąt** na mapie, aby zobaczyć mieszkania "
    "w wybranym obszarze wraz z ich wynikami ruchu drogowego."
)

# ---------------------------------------------------------------------------
# Build Folium map
# ---------------------------------------------------------------------------
KRAKOW_CENTER = [50.0614, 19.9366]

m = folium.Map(location=KRAKOW_CENTER, zoom_start=13, tiles="CartoDB positron")

# Draw plugin — allows the user to draw polygons and rectangles
draw = Draw(
    draw_options={
        "polygon": True,
        "rectangle": True,
        "polyline": False,
        "circle": False,
        "marker": False,
        "circlemarker": False,
    },
    edit_options={"edit": False, "remove": True},
)
draw.add_to(m)


def marker_color(score: float) -> str:
    """Return a Folium marker color based on traffic score."""
    if score < 35:
        return "green"
    elif score <= 70:
        return "orange"
    return "red"


# Add all apartment markers
for _, apt in apartments_df.iterrows():
    color = marker_color(apt["traffic_score"])
    popup_html = (
        f"<b>{apt['title']}</b><br>"
        f"Dzielnica: {apt['district']}<br>"
        f"Cena: {int(apt['price']):,} PLN<br>"
        f"Powierzchnia: {apt['area']} m²<br>"
        f"Pokoje: {apt['rooms']}<br>"
        f"Cena/m²: {apt['price_per_m2']:,} PLN<br>"
        f"Wynik ruchu: <b>{apt['traffic_score']}</b><br>"
        f"<a href='{apt['url']}' target='_blank'>Zobacz ogłoszenie</a>"
    )
    folium.Marker(
        location=[apt["lat"], apt["lon"]],
        popup=folium.Popup(popup_html, max_width=260),
        tooltip=apt["title"],
        icon=folium.Icon(color=color, icon="home", prefix="fa"),
    ).add_to(m)

# Optionally add traffic measurement point markers
if show_traffic_pts:
    for _, tp in traffic_df.iterrows():
        folium.CircleMarker(
            location=[tp["lat"], tp["lon"]],
            radius=6,
            color="#cc0000",
            fill=True,
            fill_color="#ff4444",
            fill_opacity=0.7,
            tooltip=f"{tp['name']} — ruch: {int(tp['traffic_level'])}",
        ).add_to(m)

# ---------------------------------------------------------------------------
# Render map and capture drawn shape
# ---------------------------------------------------------------------------
st_data = st_folium(m, width="100%", height=550, returned_objects=["last_active_drawing"])

# ---------------------------------------------------------------------------
# Process drawn polygon (if any)
# ---------------------------------------------------------------------------
poly_coords = extract_drawn_polygon(st_data)

if poly_coords:
    # --- Spatial search: KDTree prefilter + Shapely point-in-polygon ---
    inside_df = search_engine.search_inside_polygon(poly_coords)

    if inside_df.empty:
        st.info("Brak mieszkań w zaznaczonym obszarze.")
    else:
        # Recalculate traffic score with current radius (scores may change if slider moved)
        inside_df = inside_df.copy()
        inside_df["traffic_score"] = inside_df.apply(
            lambda row: scorer.calculate_score_for_point(row["lon"], row["lat"], radius_meters),
            axis=1,
        )

        # Apply sidebar filters
        filtered_df = inside_df[
            (inside_df["traffic_score"] <= max_traffic)
        ].copy()

        st.subheader(f"Znalezione mieszkania: {len(filtered_df)}")

        if filtered_df.empty:
            st.warning("Żadne mieszkanie nie spełnia wybranych kryteriów filtrowania.")
        else:
            # --- Optional convex hull ---
            if show_hull and len(filtered_df) >= 3:
                # Convert selected apartment coordinates to metric for ConvexHull
                hull_xy = [
                    transformer.to_meters(row.lon, row.lat)
                    for row in filtered_df.itertuples()
                ]
                hull_vertices_xy = calculate_convex_hull(hull_xy)

                if hull_vertices_xy:
                    # Convert hull vertices back to GPS degrees for Folium
                    hull_latlon = [
                        transformer.to_degrees(x, y)[::-1]  # (lon,lat) → (lat,lon)
                        for x, y in hull_vertices_xy
                    ]
                    # Close the polygon for display
                    hull_latlon.append(hull_latlon[0])
                    folium.PolyLine(
                        locations=hull_latlon,
                        color="blue",
                        weight=2,
                        dash_array="8",
                        tooltip="Wypukła otoczka wybranych mieszkań",
                    ).add_to(m)
                    st.caption(
                        "Niebieska linia przerywana = wypukła otoczka (convex hull): "
                        "najmniejszy wypukły wielokąt zawierający wszystkie wybrane mieszkania."
                    )

            # --- Table ---
            display_cols = ["title", "district", "price", "area", "rooms", "price_per_m2", "traffic_score", "url"]
            st.dataframe(
                filtered_df[display_cols].rename(columns={
                    "title": "Tytuł",
                    "district": "Dzielnica",
                    "price": "Cena (PLN)",
                    "area": "Pow. (m²)",
                    "rooms": "Pokoje",
                    "price_per_m2": "Cena/m²",
                    "traffic_score": "Wynik ruchu",
                    "url": "Link",
                }),
                use_container_width=True,
                hide_index=True,
            )

            # Legend
            st.markdown(
                "**Legenda kolorów markerów:** "
                "🟢 wynik < 35 (małe natężenie)  |  "
                "🟠 35–70 (umiarkowane)  |  "
                "🔴 > 70 (duże natężenie)"
            )
else:
    st.info("Narysuj wielokąt lub prostokąt na mapie, aby wybrać mieszkania.")

# ---------------------------------------------------------------------------
# Footer note
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.caption(
    "Algorytmy: KDTree (scipy) jako indeks przestrzenny, "
    "Shapely point-in-polygon (covers), "
    "pyproj EPSG:4326→EPSG:2178, "
    "ConvexHull (scipy)."
)