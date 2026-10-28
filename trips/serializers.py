from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    """Require two nonblank locations and strip surrounding whitespace."""

    # CharField already rejects missing and blank values before custom validation.
    start = serializers.CharField(max_length=255, trim_whitespace=True)
    finish = serializers.CharField(max_length=255, trim_whitespace=True)
