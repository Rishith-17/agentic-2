"""Google Places API skill for searching nearby locations."""

from typing import Any
import logging

from app.config import get_settings
from app.skills.base import SkillBase
from app.utils.dep_check import require

logger = logging.getLogger(__name__)

class PlacesSkill(SkillBase):
    name = "places"
    description = "Searches for nearby places like restaurants, hospitals, ATMs etc. using Google Places API."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Type of place to search for (e.g. restaurants, hospital, ATM)"},
                "location": {"type": "string", "description": "Current location or city. Use 'current' for default city"}
            },
            "required": ["query"]
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = get_settings()
        api_key = settings.google_maps_api_key

        if not api_key:
            return {
                "error": "Google Maps API key not configured. Please set GOOGLE_MAPS_API_KEY in .env."
            }

        if action not in ["search_nearby"]:
            return {"error": f"Unknown action: {action}"}

        query = parameters.get("query")
        location_param = parameters.get("location", "current")
        
        if not query:
            return {"error": "Query (e.g., 'restaurants') must be provided."}

        try:
            require("googlemaps", "googlemaps>=4.10.0")
            import googlemaps
            gmaps = googlemaps.Client(key=api_key)
            
            # Resolve location string to coordinates
            search_location = location_param
            if search_location.lower() == 'current':
                search_location = settings.openweather_city_default
                
            geocode_result = gmaps.geocode(search_location)
            if not geocode_result:
                return {"error": f"Could not geocode the location: {search_location}"}
                
            location_latlng = geocode_result[0]["geometry"]["location"]

            places_result = gmaps.places(
                query=query,
                location=location_latlng,
                radius=10000  # 10km radius
            )

            if_status = places_result.get('status')
            if if_status != 'OK':
                if if_status == 'ZERO_RESULTS':
                    return {"result": f"No places found matching '{query}' near {search_location}."}
                return {"error": f"Places API returned status: {if_status}"}

            results = places_result.get("results", [])[:5]  # limit to top 5
            formatted_results = []
            
            for place in results:
                formatted_results.append({
                    "name": place.get("name"),
                    "rating": place.get("rating", "N/A"),
                    "address": place.get("formatted_address", "No address provided")
                })
                
            lines = [f"📍 {p['name']} (Rating: {p['rating']}) - {p['address']}" for p in formatted_results]
            msg = f"Found {len(formatted_results)} places near {search_location}:\n" + "\n".join(lines)
            return {
                "location_used": search_location,
                "places": formatted_results,
                "status": "success",
                "message": msg,
                "summary_text": msg,
                "skill_type": "places"
            }
            
        except Exception as e:
            logger.error("Google Places API error: %s", e)
            return {"error": f"Failed to search places: {str(e)}"}
