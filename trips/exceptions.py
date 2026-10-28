class TripPlanningError(Exception):
    """Raised when geocoding or routing cannot produce a usable trip."""


class MapServiceError(Exception):
    """A map provider returned an unusable response."""
