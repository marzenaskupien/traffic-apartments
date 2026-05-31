from pathlib import Path
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
from urllib.parse import quote_plus


DISTRICT_CENTERS = {
    "Krowodrza": (50.0735, 19.9220),
    "Grzegórzki": (50.0575, 19.9605),
    "Podgórze": (50.0465, 19.9560),
    "Kazimierz": (50.0510, 19.9445),
    "Nowa Huta": (50.0720, 20.0370),
    "Bronowice": (50.0815, 19.8840),
    "Dębniki": (50.0455, 19.9020),
    "Prądnik Czerwony": (50.0880, 19.9740),
}


def distance_km(lat1, lon1, lat2, lon2):
    """Liczy przybliżoną odległość między dwoma punktami GPS w kilometrach."""
    r = 6371.0

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c


def assign_district(lat, lon):
    """Przypisuje najbliższą dzielnicę z listy DISTRICT_CENTERS."""
    nearest_district = None
    nearest_distance = float("inf")

    for district, (district_lat, district_lon) in DISTRICT_CENTERS.items():
        dist = distance_km(lat, lon, district_lat, district_lon)

        if dist < nearest_distance:
            nearest_distance = dist
            nearest_district = district

    return nearest_district

RAW_DATA_DIR = Path("data/raw")
OUTPUT_FILE = Path("data/apartments.csv")

# Wczytujemy wszystkie pliki CSV z folderu data/raw
csv_files = list(RAW_DATA_DIR.glob("*.csv"))

if not csv_files:
    raise FileNotFoundError("Nie znaleziono plików CSV w folderze data/raw")

all_dataframes = []

for file in csv_files:
    print(f"Wczytuję plik: {file}")
    df = pd.read_csv(file)
    all_dataframes.append(df)

# Łączymy wszystkie pliki w jedną tabelę
df_all = pd.concat(all_dataframes, ignore_index=True)

print("Dostępne miasta w danych:")
print(df_all["city"].dropna().unique())

# Filtrujemy tylko Kraków
# W Kaggle może być zapisane jako Krakow albo Kraków
krakow = df_all[
    df_all["city"]
    .astype(str)
    .str.lower()
    .isin(["krakow", "kraków"])
].copy()

print(f"Liczba ofert z Krakowa: {len(krakow)}")

if krakow.empty:
    raise ValueError("Nie znaleziono ofert z Krakowa. Sprawdź, jak dokładnie zapisane jest miasto w kolumnie city.")

# Usuwamy rekordy bez najważniejszych danych
krakow = krakow.dropna(
    subset=["price", "squareMeters", "rooms", "latitude", "longitude"]
)

# Opcjonalnie ograniczamy liczbę rekordów, np. do 200
# Jeśli chcesz wszystkie, usuń tę linię albo zakomentuj ją znakiem #
krakow = krakow.head(8000).copy()

krakow=krakow.reset_index(drop=True)

apartments = pd.DataFrame()

apartments["id"] = range(1, len(krakow) + 1)

apartments["title"] = (
    "Mieszkanie "
    + krakow["rooms"].astype(int).astype(str)
    + "-pokojowe, "
    + krakow["squareMeters"].round(1).astype(str)
    + " m2"
)

# W danych Kaggle nie ma dzielnicy, więc na razie wpisujemy Kraków.
# Później można dodać prawdziwe dzielnice na podstawie współrzędnych.
apartments["district"] = krakow.apply(
    lambda row: assign_district(row["latitude"], row["longitude"]),
    axis=1
)

apartments["price"] = krakow["price"].round(0).astype(int)
apartments["area"] = krakow["squareMeters"].round(2)
apartments["rooms"] = krakow["rooms"].astype(int)
apartments["lat"] = krakow["latitude"]
apartments["lon"] = krakow["longitude"]

# Kaggle nie ma linków do konkretnych ofert, więc dajemy link do źródła danych
apartments["url"] = apartments.apply(
    lambda row: "https://www.google.com/search?q="
    + quote_plus(
        f"mieszkanie Kraków {row['district']} {row['rooms']} pokoje {row['area']} m2"
    ),
    axis=1
)

# Zapisujemy gotowy plik dla aplikacji
apartments.to_csv(OUTPUT_FILE, index=False)

print(f"Zapisano plik: {OUTPUT_FILE}")
print(apartments.head())