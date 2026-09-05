from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import TemplateView

from decisions.views import (
    DecisionDetailView,
    DecisionListView,
    DecisionUpdateStatusView,
    DecisionUpdateView,
)
from leagues.dashboard import ActivityView, MoreView, OverviewView, ScheduleFragmentView, TeamView
from leagues.views import MatchupListView, TradeOfferListView, mcp_authorize

from .health import health

urlpatterns = [
    path("overview/", OverviewView.as_view(), name="overview"),
    path("my-team/", TeamView.as_view(), name="my-team"),
    path("player-schedule/", ScheduleFragmentView.as_view(), name="player-schedule"),
    path("activity/", ActivityView.as_view(), name="activity"),
    path("more/", MoreView.as_view(), name="more"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("decisions/", DecisionListView.as_view(), name="decision-list"),
    path("decisions/update/", DecisionUpdateView.as_view(), name="decision-update"),
    path("decisions/update/status/", DecisionUpdateStatusView.as_view(), name="decision-update-status"),
    path("decisions/<int:pk>/", DecisionDetailView.as_view(), name="decision-detail"),
    path("matchups/", MatchupListView.as_view(), name="matchup-list"),
    path("trades/", TradeOfferListView.as_view(), name="trade-list"),
    path("mcp/authorize/confirm/", mcp_authorize, name="mcp-authorize"),
    path("", TemplateView.as_view(template_name="leagues/home.html"), name="home"),
    path("fantasy-backend/", admin.site.urls),
    path("health/", health, name="health"),
]
