from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=255, trim_whitespace=True)
    finish = serializers.CharField(max_length=255, trim_whitespace=True)

    def validate_start(self, value):
        if not value:
            raise serializers.ValidationError("Start location is required.")
        return value

    def validate_finish(self, value):
        if not value:
            raise serializers.ValidationError("Finish location is required.")
        return value
