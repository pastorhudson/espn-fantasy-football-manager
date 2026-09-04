from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

from .health import health

urlpatterns = [
    path("", TemplateView.as_view(template_name="leagues/home.html"), name="home"),
    path("fantasy-backend/", admin.site.urls),
    path("health/", health, name="health"),
]
