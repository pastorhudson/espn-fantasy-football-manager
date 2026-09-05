"""Mobile views: saved data renders immediately; live schedules load separately."""
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpResponseBadRequest
from django.views.generic import TemplateView

from .matchups import my_matchup_data
from .mcp_data import manager_roster_data
from .nfl_schedule import player_schedule_data
from .transactions import league_transactions_data


class LeaguePage(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "decisions.view_decision"


class OverviewView(LeaguePage):
    template_name = "leagues/overview.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **manager_roster_data(),
                "mine": my_matchup_data(), "activity": league_transactions_data(limit=5)}


class TeamView(LeaguePage):
    template_name = "leagues/team.html"

    def get_context_data(self, **kwargs):
        data = manager_roster_data()
        group = self.request.GET.get("group", "all")
        if group not in {"all", "starters", "bench"}:
            group = "all"
        players = (data.get("roster") or {}).get("players", [])
        for player in players:
            player["is_starter"] = player["lineup_slot_id"] not in (20, 21, 22)
        players = [p for p in players if group == "all" or p["is_starter"] == (group == "starters")]
        return {**super().get_context_data(**kwargs), **data, "players": players, "group": group}


class ScheduleFragmentView(LeaguePage):
    template_name = "leagues/schedule_fragment.html"

    def get(self, request, *args, **kwargs):
        try:
            self.data = player_schedule_data()
        except ValueError:
            self.data = {"available": False, "players": []}
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        group = self.request.GET.get("group", "all")
        data = self.data
        players = data.get("players", [])
        if group in {"starters", "bench"}:
            players = [p for p in players if p["is_starter"] == (group == "starters")]
        return {**super().get_context_data(**kwargs), "schedule": data, "players": players,
                "overview": self.request.GET.get("overview") == "1",
                "attention": [p for p in players if p.get("injury_status")
                              and p["injury_status"] != "ACTIVE"]}


class ActivityView(LeaguePage):
    template_name = "leagues/activity.html"

    def get(self, request, *args, **kwargs):
        try:
            self.team_id = int(request.GET["team"]) if request.GET.get("team") else None
        except ValueError:
            return HttpResponseBadRequest("Team must be an ESPN team ID.")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from .mcp_data import configured_league
        league = configured_league()
        return {**super().get_context_data(**kwargs),
                "activity": league_transactions_data(team_id=self.team_id),
                "teams": league.teams.all() if league else [], "selected_team": self.team_id}


class MoreView(LeaguePage):
    template_name = "leagues/more.html"
