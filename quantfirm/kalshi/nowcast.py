"""Nowcast / ensemble helpers for weather and macro Kalshi books.

Weather daily highs settle on the NWS Daily Climate Report (CLI) for a
named station — Central Park (KNYC) for NYC, not LGA/JFK. Hourly temp
markets settle on The Weather Company, not NWS. Ensemble members from
Open-Meteo (GFS GEFS, ECMWF IFS EPS) are a *model* distribution; they are
not the settlement print. The edge, if any, is turning that distribution
into bracket probabilities faster than the book.

Macro: CPI/core vs Cleveland Fed inflation nowcasting (monthly, not
annualized), GDP vs Atlanta Fed GDPNow (FRED GDPNOW, SAAR), weekly
claims vs the seasonal pattern on FRED ICSA. Edge is print-speed:
map the number onto nested "above X" strikes before the book reprices.
There is no overnight Sunday print — do not fake one.
"""

from __future__ import annotations

from dataclasses import dataclass


# NWS climate stations used by Kalshi daily high/low (help center +
# contract terms). Coordinates are the climate site, not the airport
# as a substitute when the CLI is a park/city office.
WEATHER_STATIONS = {
    "KXHIGHNY": {
        "city": "nyc", "station": "KNYC", "name": "Central Park NY",
        "lat": 40.7789, "lon": -73.9692, "tz": "America/New_York",
        "wfo": "okx", "kind": "high",
    },
    "KXHIGHTBOS": {
        "city": "boston", "station": "KBOS", "name": "Boston Logan",
        "lat": 42.3606, "lon": -71.0106, "tz": "America/New_York",
        "wfo": "box", "kind": "high",
    },
    "KXHIGHCHI": {
        "city": "chicago", "station": "KORD", "name": "Chicago O'Hare",
        "lat": 41.9742, "lon": -87.9073, "tz": "America/Chicago",
        "wfo": "lot", "kind": "high",
    },
    "KXHIGHHOU": {
        "city": "houston", "station": "KIAH", "name": "Houston Intercontinental",
        "lat": 29.9844, "lon": -95.3414, "tz": "America/Chicago",
        "wfo": "hgx", "kind": "high",
    },
    "KXDENHIGH": {
        "city": "denver", "station": "KDEN", "name": "Denver Intl",
        "lat": 39.8561, "lon": -104.6737, "tz": "America/Denver",
        "wfo": "bou", "kind": "high",
    },
    "HIGHMIA": {
        "city": "miami", "station": "KMIA", "name": "Miami Intl",
        "lat": 25.7959, "lon": -80.2870, "tz": "America/New_York",
        "wfo": "mfl", "kind": "high",
    },
    "KXHIGHLAX": {
        "city": "la", "station": "KLAX", "name": "Los Angeles Intl",
        "lat": 33.9425, "lon": -118.4081, "tz": "America/Los_Angeles",
        "wfo": "lox", "kind": "high",
    },
    "KXHIGHMIA": {
        "city": "miami", "station": "KMIA", "name": "Miami Intl",
        "lat": 25.7959, "lon": -80.2870, "tz": "America/New_York",
        "wfo": "mfl", "kind": "high",
    },
    "KXHIGHDEN": {
        "city": "denver", "station": "KDEN", "name": "Denver Intl",
        "lat": 39.8561, "lon": -104.6737, "tz": "America/Denver",
        "wfo": "bou", "kind": "high",
    },
    "RAINNY": {
        "city": "nyc", "station": "KNYC", "name": "Central Park NY",
        "lat": 40.7789, "lon": -73.9692, "tz": "America/New_York",
        "wfo": "okx", "kind": "rain",
    },
    "KXRAINDENM": {
        "city": "denver", "station": "KDEN", "name": "Denver Intl",
        "lat": 39.8561, "lon": -104.6737, "tz": "America/Denver",
        "wfo": "bou", "kind": "rain",
    },
}


# Open-Meteo ensemble models that actually cover CONUS and update often.
# HRRR is high-res but not an ensemble on this API; GEFS 0.25 is the
# NOAA ensemble. ECMWF IFS 0.25 is the 51-member EPS.
ENSEMBLE_MODELS = ("gfs025", "ecmwf_ifs025")

OPEN_METEO_ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
NWS_OBS = "https://api.weather.gov/stations/{station}/observations/latest"
NWS_CLI = "https://api.weather.gov/stations/{station}/observations"

# FRED csv (no key required for these series).
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
FRED_GDPNOW = "GDPNOW"
FRED_ICSA = "ICSA"          # weekly initial claims, SA
FRED_CCSA = "CCSA"          # continued claims
FRED_CPI = "CPIAUCSL"      # monthly CPI index SA
FRED_CPILFESL = "CPILFESL"  # core CPI index SA

CLEVELAND_NOWCAST = (
    "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
)
GDPNOW_PAGE = "https://www.atlantafed.org/cqer/research/gdpnow"


@dataclass(frozen=True)
class NowcastPoint:
    source: str
    name: str
    value: float
    asof: str | None = None
    unit: str = ""
    note: str = ""


def mom_from_index(prev: float, now: float) -> float:
    """Non-annualized month-over-month percent change (CPI convention)."""
    if prev == 0:
        return 0.0
    return 100.0 * (now / prev - 1.0)


def seasonal_claims_expect(history: list[tuple[str, float]],
                            weeks: int = 5) -> dict | None:
    """Naive seasonal: median of the same calendar week over ``weeks`` years,
    plus the last 4-week change. ``history`` is (YYYY-MM-DD, value) ascending.
    """
    if len(history) < 8:
        return None
    last_d, last_v = history[-1]
    # ISO week of last print
    from datetime import date
    d = date.fromisoformat(last_d[:10])
    iso = d.isocalendar()
    same = []
    for hd, hv in history[:-1]:
        try:
            xd = date.fromisoformat(hd[:10])
        except ValueError:
            continue
        xi = xd.isocalendar()
        if xi.week == iso.week and iso.year - xi.year <= weeks:
            same.append(hv)
    last4 = [v for _, v in history[-5:-1]]
    drift = (last_v - last4[0] / 1.0) / 4.0 if len(last4) == 4 else 0.0
    seas = sorted(same)[len(same) // 2] if same else last_v
    return {
        "last": last_v,
        "last_date": last_d,
        "seasonal_median": seas,
        "n_seasonal": len(same),
        "expect": seas,
        "mom_drift": drift,
    }


def event_date_from_ticker(event_ticker: str) -> str | None:
    """Kalshi weather/macro event date from the ticker, not close_time.

    Close is the next morning UTC (KXHIGHNY-26SEP11 closes ~05:00Z on the
    12th) and would map to the wrong local day.
    """
    import re
    from datetime import datetime as _dt
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})$", str(event_ticker or ""))
    if not m:
        return None
    try:
        return _dt.strptime(m.group(1) + m.group(2) + m.group(3),
                            "%y%b%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        d, raw = parts[0].strip(), parts[1].strip()
        if raw in (".", "", "NA"):
            continue
        try:
            rows.append((d, float(raw)))
        except ValueError:
            continue
    return rows
