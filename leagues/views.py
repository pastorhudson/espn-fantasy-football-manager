
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views.generic import TemplateView

from .mcp_auth import approve_request
from .trades import list_offer_evidence


class TradeOfferListView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "decisions.view_decision"
    template_name = "leagues/trades.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "offers": list_offer_evidence()}


@login_required
@permission_required("decisions.view_decision", raise_exception=True)
def mcp_authorize(request):
    request_token = request.GET.get("request") or request.POST.get("request")
    if not request_token:
        return HttpResponseBadRequest("Missing authorization request.")
    if request.method == "POST":
        redirect_url = approve_request(request_token, request.user)
        if redirect_url:
            return HttpResponseRedirect(redirect_url)
        return HttpResponseBadRequest("Authorization expired. Return to ChatGPT and connect again.")
    return render(request, "leagues/mcp_authorize.html", {"request_token": request_token})
