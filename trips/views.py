from time import perf_counter

from requests.exceptions import RequestException
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import MapServiceError, TripPlanningError
from .serializers import RouteRequestSerializer
from .services import plan_trip


class PlanRouteView(APIView):
    """POST /api/route/ — plan a US driving route between two places."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start = serializer.validated_data["start"]
        finish = serializer.validated_data["finish"]

        timings = {}
        started = perf_counter()
        try:
            result = plan_trip(start, finish, timings=timings)
        except TripPlanningError as exc:
            response = Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (RequestException, MapServiceError):
            response = Response(
                {"error": "Map or routing service is temporarily unavailable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        else:
            response = Response(result)

        timings["total"] = (perf_counter() - started) * 1000
        response["Server-Timing"] = ", ".join(
            f"{name};dur={duration:.2f}" for name, duration in timings.items()
        )
        return response
