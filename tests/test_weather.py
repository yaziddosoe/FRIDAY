import asyncio
import urllib.parse

import pytest

import tools
import weather


def _sample_payload() -> dict:
    return {
        "current_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "wind_speed_10m": "km/h",
        },
        "current": {
            "temperature_2m": 26.6,
            "weather_code": 2,
            "relative_humidity_2m": 84.0,
            "wind_speed_10m": 10.2,
        },
        "daily": {
            "temperature_2m_max": [31.5],
            "temperature_2m_min": [24.7],
        },
    }


class TestWeatherCodeToText:
    def test_known_codes_map_to_plain_text(self) -> None:
        assert weather.weather_code_to_text(0) == "clear skies"
        assert weather.weather_code_to_text(3) == "overcast"
        assert weather.weather_code_to_text(61) == "light rain"
        assert weather.weather_code_to_text(95) == "thunderstorms"

    def test_unknown_code_gets_generic_text(self) -> None:
        assert weather.weather_code_to_text(999) == "challenging weather"


class TestFormatCurrent:
    def test_sentence_has_core_values(self) -> None:
        rendered = weather.format_current(_sample_payload(), "Paramaribo, Suriname")
        assert "26.6" in rendered
        assert "31.5" in rendered
        assert "24.7" in rendered
        assert "Paramaribo" in rendered
        assert "partly cloudy" in rendered


class TestFetchWeather:
    @staticmethod
    def _fake_json(hit_order: list[str]) -> dict:
        def fake(url: str) -> dict:
            if "geocoding-api" in url:
                hit_order.append("geocode")
                return {
                    "results": [
                        {
                            "name": "Paramaribo",
                            "country": "Suriname",
                            "latitude": -5.87,
                            "longitude": -55.17,
                        }
                    ]
                }
            hit_order.append("forecast")
            return _sample_payload()

        return fake

    def test_default_city_when_place_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order: list[str] = []
        monkeypatch.setattr(weather, "_fetch_json", self._fake_json(order))
        result = weather.fetch_weather("", default_city="Paramaribo")
        assert "26.6" in result
        assert order == ["geocode", "forecast"]

    def test_given_place_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, str] = {}

        def fake(url: str) -> dict:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if "geocoding-api" in url:
                seen["name"] = query["name"][0]
            return self._fake_json([])(url)

        monkeypatch.setattr(weather, "_fetch_json", fake)
        weather.fetch_weather("Georgetown", default_city="Paramaribo")
        assert seen["name"] == "Georgetown"

    def test_geocode_hits_are_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        order: list[str] = []
        monkeypatch.setattr(weather, "_fetch_json", self._fake_json(order))
        # "Cachetown" is unlikely to have been geocoded by another test.
        weather.fetch_weather("Cachetown", default_city="Cachetown")
        weather.fetch_weather("Cachetown", default_city="Cachetown")
        assert order == ["geocode", "forecast", "forecast"]

    def test_unknown_place_raises_weather_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(weather, "_fetch_json", lambda url: {"results": []})
        with pytest.raises(weather.WeatherError):
            weather.fetch_weather("Atlantis")

    def test_network_failure_raises_weather_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*args, **kwargs):
            raise OSError("offline")

        monkeypatch.setattr(weather.urllib.request, "urlopen", boom)
        with pytest.raises(weather.WeatherError):
            weather.fetch_weather("Paramaribo")


class TestGetWeatherTool:
    async def test_returns_formatted_weather(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            weather,
            "_fetch_json",
            lambda url: (
                _sample_payload()
                if "geocoding-api" not in url
                else {
                    "results": [
                        {
                            "name": "Paramaribo",
                            "country": "Suriname",
                            "latitude": -5.87,
                            "longitude": -55.17,
                        }
                    ]
                }
            ),
        )
        result = await tools.get_weather(None)
        assert "26.6" in result

    async def test_weather_error_becomes_friendly_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*args, **kwargs):
            raise weather.WeatherError("I could not find a place called 'Atlantis'.")

        monkeypatch.setattr(weather, "fetch_weather", boom)
        result = await tools.get_weather(None, place="Atlantis")
        assert "could not find" in result.lower()

    async def test_unexpected_failure_falls_back_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(weather, "fetch_weather", boom)
        result = await tools.get_weather(None)
        assert "could not fetch" in result.lower()


class TestSearchWebTool:
    async def test_results_surface_to_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tools,
            "_ddgs_search",
            lambda q: "- Waste 2030 report: recycling\n- Greener cities",
        )
        result = await tools.search_web(None, query="waste recycling study")
        assert "Greener cities" in result

    async def test_empty_results_friendly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tools, "_ddgs_search", lambda q: "")
        result = await tools.search_web(None, query="nothing")
        assert "rephrasing" in result

    async def test_backend_failure_friendly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(q: str) -> str:
            raise RuntimeError("ddgs blocked us")

        monkeypatch.setattr(tools, "_ddgs_search", boom)
        result = await tools.search_web(None, query="anything")
        assert "snag" in result


class TestRemainingToolsAwaitable:
    async def test_tools_return_coroutines_like_livekit_executor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The voice ToolExecutor awaits every tool result unconditionally, so the
        # remaining sync tools must be async too or they crash like launch_app did.
        class StubStore:
            def add_fact(self, fact: str) -> None:
                pass

            def forget_fact(self, keyword: str) -> int:
                return 0

        monkeypatch.setattr(tools, "MemoryStore", lambda: StubStore())
        calls: dict[str, dict[str, object]] = {
            "get_current_datetime": {},
            "remember_fact": {"fact": "x"},
            "forget_fact": {"keyword": "x"},
        }
        for name, kwargs in calls.items():
            result = getattr(tools, name)(None, **kwargs)
            assert asyncio.iscoroutine(result), (
                f"{name} is not awaitable; the voice executor cannot run it"
            )
            assert isinstance(await result, str)
