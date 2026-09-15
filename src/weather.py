"""Keyless current-weather and today's-forecast lookups via Open-Meteo.

The generic web-search tool cannot answer "what is the weather right now" well,
so weather questions use this dedicated source instead. Open-Meteo needs no API
key, returns structured JSON, and resolves arbitrary place names through its
geocoding endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("weather")

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 12.0

# Open-Meteo WMO weather-interpretation codes -> plain-text conditions.
_WMO_TEXT: dict[int, str] = {
    0: "clear skies",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}

_GEOCODE_CACHE: dict[str, tuple[Place, float]] = {}
_GEOCODE_TTL = 3600.0


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    latitude: float
    longitude: float


class WeatherError(RuntimeError):
    pass


def weather_code_to_text(code: int) -> str:
    return _WMO_TEXT.get(code, "challenging weather")


def format_current(data: dict, where: str) -> str:
    current = data["current"]
    units = data["current_units"]
    daily = data["daily"]

    temp = current["temperature_2m"]
    temp_unit = units["temperature_2m"]
    condition = weather_code_to_text(current["weather_code"])
    high = daily["temperature_2m_max"][0]
    low = daily["temperature_2m_min"][0]

    parts = [f"In {where} it is currently {temp} {temp_unit} and {condition}."]
    humidity = current.get("relative_humidity_2m")
    if humidity is not None:
        parts.append(f"Humidity is {humidity}{units.get('relative_humidity_2m', '%')}.")
    wind = current.get("wind_speed_10m")
    if wind is not None:
        parts.append(f"Wind is {wind} {units.get('wind_speed_10m', 'km/h')}.")
    parts.append(
        f"Today's high is {high} {temp_unit} and the low is {low} {temp_unit}."
    )
    return " ".join(parts)


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Weather request to Open-Meteo failed: %s", exc)
        raise WeatherError(
            "I could not reach the weather service right now; please try again later."
        ) from exc


def _geocode(place: str) -> Place:
    key = place.lower()
    cached = _GEOCODE_CACHE.get(key)
    if cached is not None and time.time() - cached[1] < _GEOCODE_TTL:
        return cached[0]
    url = _GEOCODING_URL + "?" + urllib.parse.urlencode({"name": place, "count": 1})
    data = _fetch_json(url)
    results = data.get("results") or []
    if not results:
        raise WeatherError(f"I could not find a place called '{place}'.")
    top = results[0]
    found = Place(
        name=top.get("name", place),
        country=top.get("country", ""),
        latitude=top["latitude"],
        longitude=top["longitude"],
    )
    _GEOCODE_CACHE[key] = (found, time.time())
    return found


def _forecast(loc: Place) -> dict:
    params = {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    }
    url = _FORECAST_URL + "?" + urllib.parse.urlencode(params)
    return _fetch_json(url)


def fetch_weather(place: str = "", default_city: str | None = None) -> str:
    if not default_city:
        default_city = os.environ.get("FRIDAY_CITY", "Paramaribo")
    name = (place or default_city).strip()
    if not name:
        raise WeatherError("I need a city or place name to check the weather.")
    loc = _geocode(name)
    data = _forecast(loc)
    where = loc.name + (f", {loc.country}" if loc.country else "")
    return format_current(data, where)
