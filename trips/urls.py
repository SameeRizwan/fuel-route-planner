from django.urls import path

from .views import PlanRouteView

urlpatterns = [
    path("route/", PlanRouteView.as_view(), name="plan-route"),
]
