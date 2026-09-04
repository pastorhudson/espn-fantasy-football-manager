from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import TemplateView

from decisions.views import DecisionDetailView, DecisionListView

from .health import health

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("decisions/", DecisionListView.as_view(), name="decision-list"),
    path("decisions/<int:pk>/", DecisionDetailView.as_view(), name="decision-detail"),
    path("", TemplateView.as_view(template_name="leagues/home.html"), name="home"),
    path("fantasy-backend/", admin.site.urls),
    path("health/", health, name="health"),
]
