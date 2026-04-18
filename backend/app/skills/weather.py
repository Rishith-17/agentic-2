"""WeatherAPI.com current, forecast, rain alerts."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.skills.base import SkillBase


class WeatherSkill(SkillBase):
    name = "weather"
    description = "Current weather, weekly forecast, rain alerts via WeatherAPI.com."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["current", "forecast", "rain_alert"]},
                "city": {"type": "string"},
                "rain_threshold_mm": {"type": "number"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        s = get_settings()
        key = s.weatherapi_api_key
        # 1. Try city/coords from skill parameters
        city = parameters.get("city")
        
        # 2. Try App context (set by browser geolocation or manual move)
        if not city and context and "user_location" in context:
            loc = context["user_location"]
            if loc.get("lat") and loc.get("lng"):
                city = f"{loc['lat']},{loc['lng']}"
            elif loc.get("city"):
                city = loc["city"]

        # 3. Fallback to IP-based geolocation
        if not city:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    geo_r = await client.get("http://ip-api.com/json")
                    if geo_r.status_code == 200:
                        geo_d = geo_r.json()
                        city = geo_d.get("city") or geo_d.get("regionName") or s.weatherapi_city_default
                    else:
                        city = s.weatherapi_city_default
            except Exception:
                city = s.weatherapi_city_default

        if not key:
            return {"message": "Set WEATHERAPI_API_KEY in environment"}

        base = "http://api.weatherapi.com/v1"
        async with httpx.AsyncClient(timeout=30.0) as client:
            if action in ("current", "get_weather", "get", "fetch"):
                r = await client.get(
                    f"{base}/current.json",
                    params={"key": key, "q": city, "aqi": "no"},
                )
                r.raise_for_status()
                d = r.json()
                location = d["location"]["name"]
                country  = d["location"]["country"]
                condition = d["current"]["condition"]["text"]
                temp_c   = d["current"]["temp_c"]
                feels_c  = d["current"]["feelslike_c"]
                humidity = d["current"]["humidity"]
                wind_kph = d["current"]["wind_kph"]
                msg = (
                    f"🌍 {location}, {country}\n"
                    f"🌡️ {temp_c:.1f}°C  (feels like {feels_c:.1f}°C)\n"
                    f"☁️ {condition}\n"
                    f"💧 Humidity: {humidity}%  |  💨 Wind: {wind_kph:.0f} km/h"
                )
                return {
                    "message": msg,
                    "summary_text": msg,
                    "raw": d,
                    "skill_type": "weather",
                    "data": {
                        "city": location,
                        "temp": temp_c,
                        "condition": condition,
                        "icon": d["current"]["condition"]["icon"]
                    }
                }

            if action in ("forecast", "get_forecast"):
                r = await client.get(
                    f"{base}/forecast.json",
                    params={"key": key, "q": city, "days": 3, "aqi": "no", "alerts": "no"},
                )
                r.raise_for_status()
                d = r.json()
                location = d["location"]["name"]
                lines = [f"📅 3-Day Forecast — {location}"]
                for day in d.get("forecast", {}).get("forecastday", []):
                    date = day["date"]
                    cond = day["day"]["condition"]["text"]
                    max_t = day["day"]["maxtemp_c"]
                    min_t = day["day"]["mintemp_c"]
                    rain_chance = day["day"].get("daily_chance_of_rain", 0)
                    lines.append(f"📆 {date}: {cond}, {min_t:.0f}–{max_t:.0f}°C  🌧️ {rain_chance}%")
                
                msg = "\n".join(lines) or "No forecast data"
                return {"message": msg, "summary_text": msg, "skill_type": "weather"}

            if action == "rain_alert":
                r = await client.get(
                    f"{base}/forecast.json",
                    params={"key": key, "q": city, "days": 1, "aqi": "no", "alerts": "no"},
                )
                r.raise_for_status()
                d = r.json()
                
                thresh = float(parameters.get("rain_threshold_mm") or 0.5)
                # Check next 24 hours (or current day's hours)
                forecastday = d.get("forecast", {}).get("forecastday", [])
                rainSoon = False
                if forecastday:
                    hours = forecastday[0].get("hour", [])
                    for hour in hours:
                        precip = hour.get("precip_mm", 0)
                        if precip >= thresh:
                            rainSoon = True
                            break
                
                msg = (
                    f"Rain alert ({thresh}mm+) likely in the coming hours: {rainSoon}"
                    if rainSoon
                    else "No significant rain likely today"
                )
                return {"message": msg, "summary_text": msg, "skill_type": "weather"}

        return {"message": f"Unknown action {action}"}
