# Kraków Apartment Traffic Analyzer

Lokalna aplikacja MVP do eksploracji mieszkań w Krakowie. Pozwala narysować wielokąt na interaktywnej mapie i natychmiast zobaczyć, które mieszkania znajdują się w zaznaczonym obszarze wraz z ich wynikiem natężenia ruchu.

Wszystko działa lokalnie na plikach CSV — bez API, bez bazy danych, bez Dockera.

---

## Jak uruchomić

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

Następnie otwórz http://localhost:8501 w przeglądarce.

---

## Struktura projektu

```
traffic_apartments/
│
├── app.py                    ← Punkt wejścia aplikacji Streamlit
├── requirements.txt
├── README.md
├── README_PL.md
│
├── data/
│   ├── apartments.csv        ← Przykładowe mieszkania w Krakowie
│   └── traffic_points.csv    ← Punkty pomiarowe natężenia ruchu
│
└── src/
    ├── geo/
    │   ├── __init__.py
    │   ├── transformer.py    ← Transformacja współrzędnych (EPSG:4326 ↔ EPSG:2178)
    │   ├── spatial_search.py ← Prefiltr KDTree + test punkt-w-wielokącie (Shapely)
    │   └── geometry_utils.py ← Ekstrakcja wielokąta + otoczka wypukła (ConvexHull)
    │
    ├── traffic/
    │   ├── __init__.py
    │   └── traffic_score.py  ← Wyszukiwanie w promieniu KDTree + ważenie odwrotnością odległości
    │
    └── apartments/
        ├── __init__.py
        └── loader.py         ← Wczytywanie CSV + wyliczanie ceny/m²
```

---

## Pliki CSV

### data/apartments.csv

Kolumny: `id, title, district, price, area, rooms, lat, lon, url`

Zawiera przykładowe mieszkania z krakowskich dzielnic:
Krowodrza, Grzegórzki, Podgórze, Kazimierz, Nowa Huta, Bronowice, Dębniki, Prądnik Czerwony.

### data/traffic_points.csv

Kolumny: `id, name, lat, lon, traffic_level`

Zawiera punkty pomiarowe natężenia ruchu przy głównych skrzyżowaniach i ulicach Krakowa.
`traffic_level` to wartość od 0 (brak ruchu) do 100 (duże natężenie).

---

## Zastosowane koncepcje geometrii obliczeniowej

### 1. Transformacja współrzędnych — `src/geo/transformer.py`

**Dlaczego:** Współrzędne GPS są w stopniach (EPSG:4326). Stopnie nie są jednolitą jednostką odległości — 1° długości geograficznej to ok. 111 km na równiku, ale 0 km na biegunach. KDTree i ConvexHull wymagają odległości euklidesowych, które mają sens tylko w metrycznym układzie współrzędnych.

**Rozwiązanie:** `GeoTransformer` używa `pyproj` do rzutowania współrzędnych na Układ CS2000 strefa 7 (EPSG:2178), gdzie jednostką jest metr.

Wszystkie współrzędne mieszkań, punktów ruchu i wielokątów są transformowane przed obliczeniami przestrzennymi.

### 2. KDTree jako praktyczna struktura wyszukiwania przestrzennego — dwa zastosowania

**Czym jest KDTree?**
KDTree to drzewo binarne dzielące punkty w przestrzeni, które pozwala szybko odpowiadać na pytania typu „które punkty znajdują się w odległości R od tej lokalizacji?" bez sprawdzania każdego punktu po kolei.

#### A. Prefiltr wielokąta dla mieszkań — `src/geo/spatial_search.py`

Gdy użytkownik rysuje wielokąt, nie sprawdzamy od razu każdego mieszkania przez Shapely (co byłoby O(n) na zapytanie). Zamiast tego:

1. Transformujemy wierzchołki wielokąta do metrów.
2. Budujemy wielokąt Shapely.
3. Obliczamy bounding box wielokąta.
4. Obliczamy środek bounding boxa i promień wyszukiwania = połowa przekątnej.
5. Wywołujemy `KDTree.query_ball_point(center, radius)` → szybka lista kandydatów.
6. Dokładny test Shapely wykonujemy tylko na tym małym zbiorze kandydatów.

#### B. Wynik ruchu — `src/traffic/traffic_score.py`

Dla każdego mieszkania `KDTree.query_ball_point(pozycja_mieszkania, promień_w_metrach)` znajduje wszystkie punkty pomiarowe ruchu w wybranym promieniu. Następnie wynik ruchu jest obliczany jako średnia ważona odwrotnością odległości wartości `traffic_level`.

### 3. Test punkt-w-wielokącie — `src/geo/spatial_search.py`

**Algorytm:** `polygon.covers(point)` z Shapely.

`covers()` jest preferowane nad `contains()`, ponieważ `covers()` zwraca `True` również dla punktów leżących dokładnie na granicy wielokąta, podczas gdy `contains()` je wyklucza.

### 4. Wynik ruchu z ważeniem odwrotnością odległości — `src/traffic/traffic_score.py`

Dla każdego punktu pomiarowego ruchu znalezionego przez KDTree:

```
waga = 1 / (odległość + 1)
wynik_ruchu = Σ(waga × traffic_level) / Σ(waga)
```

`+1` zapobiega dzieleniu przez zero, gdy punkt ruchu znajduje się dokładnie w miejscu mieszkania. Bliższe punkty mają większy wpływ na wynik.

Jeśli w danym promieniu nie znaleziono żadnych punktów ruchu, wynik wynosi `0.0`.

### 5. Opcjonalna otoczka wypukła — `src/geo/geometry_utils.py`

**Czym jest otoczka wypukła?**
Otoczka wypukła to najmniejszy wypukły wielokąt zawierający wszystkie podane punkty. Wyobraź sobie gumkę rozciągniętą wokół najbardziej zewnętrznych punktów — powstały kształt to właśnie otoczka wypukła.

**Implementacja:** `scipy.spatial.ConvexHull` (algorytm Quickhull).

Gdy opcja jest włączona w panelu bocznym i zaznaczono co najmniej 3 mieszkania, aplikacja:
1. Konwertuje pozycje wybranych mieszkań do współrzędnych metrycznych.
2. Oblicza `ConvexHull` w przestrzeni metrycznej.
3. Konwertuje wierzchołki otoczki z powrotem do stopni GPS.
4. Rysuje wielokąt przerywaną niebieską linią na mapie Folium.

---

## Przepływ aplikacji

```
Pliki CSV (apartments.csv, traffic_points.csv)
  → transformacja współrzędnych: stopnie GPS → metry (EPSG:4326 → EPSG:2178)
  → budowanie indeksu przestrzennego KDTree (raz przy starcie, dla mieszkań i punktów ruchu)
  → użytkownik rysuje wielokąt na mapie Folium
  → prefiltr KDTree: szybki dobór kandydatów na podstawie środka + promienia bounding boxa
  → test punkt-w-wielokącie Shapely: dokładne sprawdzenie polygon.covers(point)
  → wynik ruchu: wyszukiwanie w promieniu KDTree + średnia ważona odwrotnością odległości
  → filtrowanie panelu bocznego: próg ruchu, dzielnica, liczba pokoi, cena, powierzchnia
  → markery na mapie (zielony / pomarańczowy / czerwony) + tabela DataFrame
  → opcjonalnie: otoczka wypukła narysowana wokół wybranych mieszkań
```

---

## Zastosowane algorytmy i koncepcje

| Koncepcja | Gdzie | Jak |
|---|---|---|
| **KDTree** (przestrzenne wyszukiwanie zakresowe) | `SpatialSearchEngine`, `TrafficScorer` | Prefiltr kandydatów przy wyszukiwaniu wielokątowym; wyszukiwanie pobliskich punktów ruchu |
| **Punkt-w-wielokącie** | `SpatialSearchEngine.search_inside_polygon` | `polygon.covers(point)` z Shapely |
| **Transformacja współrzędnych** | `GeoTransformer` | `pyproj` EPSG:4326 → EPSG:2178; wymagane do obliczeń odległości metrycznych |
| **Otoczka wypukła** | `calculate_convex_hull`, `app.py` | `scipy.spatial.ConvexHull`; opcjonalna wizualizacja zewnętrznej granicy |
| **Ważenie odwrotnością odległości** | `TrafficScorer.calculate_score_for_point` | `waga = 1 / (odległość + 1)` dla ważonego wyniku ruchu |

---

## Legenda kolorów markerów

- **Zielony** — wynik ruchu < 35 (małe natężenie)
- **Pomarańczowy** — wynik ruchu 35–70 (umiarkowane natężenie)
- **Czerwony** — wynik ruchu > 70 (duże natężenie)