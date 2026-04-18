"""Google Maps API skill for routing and distance calculation."""

from typing import Any
import logging

from app.config import get_settings
from app.skills.base import SkillBase
from app.utils.dep_check import require

logger = logging.getLogger(__name__)

class MapsSkill(SkillBase):
    name = "maps"
    description = "Provides directions, travel time, and distance between locations using Google Maps."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Starting location"},
                "destination": {"type": "string", "description": "Ending location"}
            },
            "required": ["origin", "destination"]
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = get_settings()
        api_key = settings.google_maps_api_key

        if not api_key:
            return {
                "error": "Google Maps API key not configured. Please set GOOGLE_MAPS_API_KEY in .env."
            }

        if action not in ["get_directions", "get_travel_time"]:
            return {"error": f"Unknown action: {action}"}

        origin = parameters.get("origin")
        destination = parameters.get("destination")
        
        if not origin or not destination:
            return {"error": "Both origin and destination must be provided."}

        try:
            require("googlemaps", "googlemaps>=4.10.0")
            import googlemaps
            gmaps = googlemaps.Client(key=api_key)
            
            # Request directions
            directions_result = gmaps.directions(
                origin,
                destination,
                mode="driving",
                departure_time="now"
            )

            if not directions_result:
                return {"error": f"No routes found between {origin} and {destination}."}

            leg = directions_result[0]['legs'][0]
            distance = leg['distance']['text']
            
            # Prefer duration_in_traffic if available
            duration = leg.get('duration_in_traffic', leg['duration'])['text']
            summary = directions_result[0].get('summary', 'Unknown route')
            
            msg = f"Directions from {leg['start_address']} to {leg['end_address']}:\nDist: {distance}, Time: {duration}\nRoute: {summary}"
            return {
                "origin": leg['start_address'],
                "destination": leg['end_address'],
                "distance": distance,
                "duration": duration,
                "route_summary": summary,
                "status": "success",
                "message": msg,
                "summary_text": msg,
                "skill_type": "maps"
            }
            
        except Exception as e:
            logger.error("Google Maps API mapping error: %s", e)
            return {"error": f"Failed to get directions: {str(e)}"}
