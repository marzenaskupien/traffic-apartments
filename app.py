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

price_min = int(apartments_df["price"].quantile(0.05))
price_max = int(apartments_df["price"].quantile(0.95))

selected_price_range = st.sidebar.slider(
    "Zakres ceny (PLN)",
    min_value=price_min,
    max_value=price_max,
    value=(price_min, price_max),
    step=50000,
)

min_area = st.sidebar.slider(
    "Minimalna powierzchnia (m²)",
    min_value=int(apartments_df["area"].min()),
    max_value=int(apartments_df["area"].max()),
    value=int(apartments_df["area"].min()),
    step=5,
)

available_rooms = sorted(apartments_df["rooms"].dropna().astype(int).unique().tolist())

selected_rooms = st.sidebar.multiselect(
    "Liczba pokoi",
    options=available_rooms,
    default=available_rooms,
)

selected_districts = st.sidebar.multiselect(
    "Dzielnice",
    options=all_districts,
    default=all_districts,
)

show_traffic_pts = st.sidebar.checkbox("Pokaż punkty pomiarowe ruchu", value=True)
show_hull = st.sidebar.checkbox("Pokaż wypukłą otoczkę (convex hull) wybranych mieszkań", value=False)
show_all_apartments = st.sidebar.checkbox(
    "Pokaż wszystkie mieszkania na mapie",
    value=False,
    help="Przy dużej liczbie rekordów lepiej zostawić wyłączone. Po zaznaczeniu obszaru pokażą się tylko znalezione mieszkania."
)
sort_option = st.sidebar.selectbox(
    "Sortuj wyniki według",
    options=[
        "Cena rosnąco",
        "Cena malejąco",
        "Cena/m² rosnąco",
        "Cena/m² malejąco",
        "Powierzchnia rosnąco",
        "Powierzchnia malejąco",
        "Wynik ruchu rosnąco",
        "Wynik ruchu malejąco",
    ],
    index=0,
)

if st.sidebar.button("Wyczyść zaznaczenie"):
    st.session_state["drawn_polygon"] = None
    st.rerun()

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

# We store the last drawn polygon in Streamlit session state.
# Thanks to this, after the user draws an area, the app can rebuild the map
# and show only apartments inside that area.
if "drawn_polygon" not in st.session_state:
    st.session_state["drawn_polygon"] = None


def marker_color(score: float) -> str:
    """Return a Folium marker color based on traffic score."""
    if score < 35:
        return "green"
    elif score <= 70:
        return "orange"
    return "red"

def sort_apartments(df: pd.DataFrame, sort_option: str) -> pd.DataFrame:
    """Sort apartments according to the selected sidebar option."""

    if sort_option == "Cena rosnąco":
        return df.sort_values(by="price", ascending=True)

    if sort_option == "Cena malejąco":
        return df.sort_values(by="price", ascending=False)

    if sort_option == "Cena/m² rosnąco":
        return df.sort_values(by="price_per_m2", ascending=True)

    if sort_option == "Cena/m² malejąco":
        return df.sort_values(by="price_per_m2", ascending=False)

    if sort_option == "Powierzchnia rosnąco":
        return df.sort_values(by="area", ascending=True)

    if sort_option == "Powierzchnia malejąco":
        return df.sort_values(by="area", ascending=False)

    if sort_option == "Wynik ruchu rosnąco":
        return df.sort_values(by="traffic_score", ascending=True)

    if sort_option == "Wynik ruchu malejąco":
        return df.sort_values(by="traffic_score", ascending=False)

    return df


def add_apartment_markers(map_obj, df: pd.DataFrame):
    """Add apartment markers from a DataFrame to a Folium map."""
    for _, apt in df.iterrows():
        color = marker_color(apt["traffic_score"])

        popup_html = (
            f"<b>{apt['title']}</b><br>"
            f"Dzielnica: {apt['district']}<br>"
            f"Cena: {int(apt['price']):,} PLN<br>"
            f"Powierzchnia: {apt['area']} m²<br>"
            f"Pokoje: {apt['rooms']}<br>"
            f"Cena/m²: {apt['price_per_m2']:,} PLN<br>"
            f"Wynik ruchu: <b>{apt['traffic_score']:.2f}</b><br>"
            f"<a href='{apt['url']}' target='_blank'>Zobacz ogłoszenie</a>"
        )

        folium.Marker(
            location=[apt["lat"], apt["lon"]],
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=apt["title"],
            icon=folium.Icon(color=color, icon="home", prefix="fa"),
        ).add_to(map_obj)


# ---------------------------------------------------------------------------
# Prepare selected apartments before rendering the map
# ---------------------------------------------------------------------------
selected_apartments = pd.DataFrame()
inside_count = 0

if st.session_state["drawn_polygon"]:
    # Search apartments inside the saved polygon
    inside_df = search_engine.search_inside_polygon(st.session_state["drawn_polygon"])
    inside_count = len(inside_df)

    if not inside_df.empty:
        inside_df = inside_df.copy()

        # Recalculate traffic score with current radius
        inside_df["traffic_score"] = inside_df.apply(
            lambda row: scorer.calculate_score_for_point(
                row["lon"],
                row["lat"],
                radius_meters
            ),
            axis=1,
        )

        # Apply sidebar filters
        selected_apartments = inside_df[
        (inside_df["traffic_score"] <= max_traffic)
        & (inside_df["price"] >= selected_price_range[0])
        & (inside_df["price"] <= selected_price_range[1])
        & (inside_df["area"] >= min_area)
        & (inside_df["rooms"].astype(int).isin(selected_rooms))
        & (inside_df["district"].isin(selected_districts))
        ].copy()

        # Sort selected apartments according to sidebar option
        selected_apartments = sort_apartments(selected_apartments, sort_option)


# ---------------------------------------------------------------------------
# Create map
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Apartment markers
# ---------------------------------------------------------------------------
# Option 1: show all apartments, only if the user explicitly enables it.
if show_all_apartments:
    add_apartment_markers(m, apartments_df)

# Option 2: if the user drew an area, show only apartments found inside it.
elif not selected_apartments.empty:
    add_apartment_markers(m, selected_apartments)


# ---------------------------------------------------------------------------
# Optional convex hull for selected apartments
# ---------------------------------------------------------------------------
if show_hull and not selected_apartments.empty and len(selected_apartments) >= 3:
    hull_xy = [
        transformer.to_meters(row.lon, row.lat)
        for row in selected_apartments.itertuples()
    ]

    hull_vertices_xy = calculate_convex_hull(hull_xy)

    if hull_vertices_xy:
        hull_latlon = [
            transformer.to_degrees(x, y)[::-1]
            for x, y in hull_vertices_xy
        ]

        hull_latlon.append(hull_latlon[0])

        folium.PolyLine(
            locations=hull_latlon,
            color="blue",
            weight=2,
            dash_array="8",
            tooltip="Wypukła otoczka wybranych mieszkań",
        ).add_to(m)


# ---------------------------------------------------------------------------
# Traffic measurement points
# ---------------------------------------------------------------------------
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
st_data = st_folium(
    m,
    width="100%",
    height=550,
    returned_objects=["last_active_drawing"],
)

# Extract newly drawn polygon from Folium
new_poly_coords = extract_drawn_polygon(st_data)

# If the user drew a new polygon, save it and rerun the app.
# On the next run, the map will show only apartments from that polygon.
if new_poly_coords and new_poly_coords != st.session_state["drawn_polygon"]:
    st.session_state["drawn_polygon"] = new_poly_coords
    st.rerun()


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------
if st.session_state["drawn_polygon"] is None:
    st.info("Narysuj wielokąt lub prostokąt na mapie, aby wybrać mieszkania.")

else:
    if inside_count == 0:
        st.info("Brak mieszkań w zaznaczonym obszarze.")

    elif selected_apartments.empty:
        st.warning(
            f"W zaznaczonym obszarze znaleziono {inside_count} mieszkań, "
            "ale żadne nie spełnia aktualnych filtrów."
        )

    else:
        st.subheader(f"Znalezione mieszkania po filtrach: {len(selected_apartments)}")

        # -----------------------------------------------------------------------
        # Statistics for the selected area
        # -----------------------------------------------------------------------
        avg_price = selected_apartments["price"].mean()
        avg_price_m2 = selected_apartments["price_per_m2"].mean()
        avg_area = selected_apartments["area"].mean()
        avg_traffic = selected_apartments["traffic_score"].mean()
        min_price = selected_apartments["price"].min()
        max_price_selected = selected_apartments["price"].max()

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Liczba mieszkań",
            len(selected_apartments)
        )

        col2.metric(
            "Średnia cena",
            f"{avg_price:,.0f} PLN"
        )

        col3.metric(
            "Średnia cena/m²",
            f"{avg_price_m2:,.0f} PLN"
        )

        col4, col5, col6, col7 = st.columns(4)

        col4.metric(
            "Średnia powierzchnia",
            f"{avg_area:.1f} m²"
        )

        col5.metric(
            "Średni wynik ruchu",
            f"{avg_traffic:.1f}/100"
        )

        col6.metric(
            "Cena min.",
            f"{min_price:,.0f} PLN"
        )

        col7.metric(
            "Cena max.",
            f"{max_price_selected:,.0f} PLN"
        )
        st.markdown("---")

        if show_hull and len(selected_apartments) >= 3:
            st.caption(
                "Niebieska linia przerywana = wypukła otoczka (convex hull): "
                "najmniejszy wypukły wielokąt zawierający wybrane mieszkania."
            )

        display_cols = [
            "title",
            "district",
            "price",
            "area",
            "rooms",
            "price_per_m2",
            "traffic_score",
            "url",
        ]

        st.dataframe(
            selected_apartments[display_cols].rename(
                columns={
                    "title": "Tytuł",
                    "district": "Dzielnica",
                    "price": "Cena (PLN)",
                    "area": "Pow. (m²)",
                    "rooms": "Pokoje",
                    "price_per_m2": "Cena/m²",
                    "traffic_score": "Wynik ruchu",
                    "url": "Link",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown(
            "**Legenda kolorów markerów:** "
            "🟢 wynik < 35 (małe natężenie)  |  "
            "🟠 35–70 (umiarkowane)  |  "
            "🔴 > 70 (duże natężenie)"
        )

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