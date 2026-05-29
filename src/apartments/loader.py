import pandas as pd


def load_apartments(path: str) -> pd.DataFrame:
    """Load apartments from a CSV file."""
    df = pd.read_csv(path)
    # Ensure numeric columns have the right type
    df["lat"] = df["lat"].astype(float)
    df["lon"] = df["lon"].astype(float)
    df["price"] = df["price"].astype(float)
    df["area"] = df["area"].astype(float)
    df["rooms"] = df["rooms"].astype(int)
    return df


def enrich_apartments(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns to the apartments DataFrame."""
    df = df.copy()
    # Price per square meter — useful for quick comparison
    df["price_per_m2"] = (df["price"] / df["area"]).round(0).astype(int)
    return df