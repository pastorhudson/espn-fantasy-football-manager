from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import DetailView, ListView

from .models import Decision

SLOT_NAMES = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB / WR", 4: "WR", 5: "WR / TE",
    6: "TE", 7: "Superflex", 8: "DT", 9: "DE", 10: "LB", 11: "DL",
    12: "CB", 13: "S", 14: "DB", 15: "DP", 16: "D/ST", 17: "K",
    18: "P", 19: "HC", 20: "Bench", 21: "IR", 22: "Bench", 23: "Flex",
}


def slot_name(value):
    return SLOT_NAMES.get(value, f"Slot {value}")


class DecisionAccessMixin(LoginRequiredMixin, PermissionRequiredMixin):
    permission_required = "decisions.view_decision"
    queryset = Decision.objects.select_related("team__league", "roster_snapshot").order_by(
        "-created_at", "-pk"
    )


class DecisionListView(DecisionAccessMixin, ListView):
    template_name = "decisions/list.html"
    context_object_name = "decisions"
    paginate_by = 20


class DecisionDetailView(DecisionAccessMixin, DetailView):
    template_name = "decisions/detail.html"
    context_object_name = "decision"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        result = self.object.recommendation
        context["assignments"] = [
            {**row, "position": slot_name(row.get("slot_id"))}
            for row in result.get("assignments", [])
        ]
        context["changes"] = [
            {**row, "from_position": slot_name(row.get("from_slot")),
             "to_position": slot_name(row.get("to_slot"))}
            for row in result.get("changes", [])
        ]
        return context
