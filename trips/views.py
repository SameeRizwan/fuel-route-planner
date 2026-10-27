from requests.exceptions import RequestException
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import TripPlanningError
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

        try:
            result = plan_trip(start, finish)
        except TripPlanningError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RequestException:
            return Response(
                {"error": "Map or routing service is temporarily unavailable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(result)
