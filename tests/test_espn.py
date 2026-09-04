import copy
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from django.core.management import call_command

from decisions.models import ManagerPolicy
from leagues.espn.client import ESPNAuthenticationError, ESPNClient, ESPNError
from leagues.espn.sync import sync_league
from leagues.models import (
    FantasyTeam,
    FreeAgentSnapshot,
    League,
    MatchupSnapshot,
    RosterSlot,
    RosterSnapshot,
)
from players.models import Player
from roster_actions.models import AuditEvent


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures" / "league.json").read_text())


def adapter(handler):
    return ESPNClient(
        123,
        2026,
        espn_s2="secret-s2",
        swid="secret-swid",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )


def response_handler(payload, calls):
    def handle(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "lm-api-reads.fantasy.espn.com"
        views = request.url.params.get_list("view")
        if "kona_player_info" in views:
            filters = json.loads(request.headers["x-fantasy-filter"])
            assert filters["players"]["filterStatus"]["value"] == ["FREEAGENT", "WAIVERS"]
            return httpx.Response(
                200,
                json={
                    "players": [
                        {
                            "player": {
                                "id": 202,
                                "fullName": "Available Player",
                                "defaultPositionId": 2,
                            },
                            "status": "FREEAGENT",
                        }
                    ]
                },
            )
        if "mTransactions2" in views:
            return httpx.Response(200, json={"transactions": []})
        return httpx.Response(200, json=payload)

    return handle


@pytest.mark.parametrize("status", [401, 403, 302])
def test_auth_errors_are_sanitized_and_not_retried(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="secret-s2 secret-swid")

    with adapter(handle) as client, pytest.raises(ESPNAuthenticationError) as caught:
        client.league()
    assert "secret" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_retries_are_bounded(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="secret-s2")

    with adapter(handle) as client, pytest.raises(ESPNError, match="temporarily unavailable"):
        client.league()
    assert len(calls) == 3


def test_timeout_then_success(payload):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("secret-s2", request=request)
        return httpx.Response(200, json=payload)

    with adapter(handle) as client:
        assert client.check_authentication()
    assert len(calls) == 2


@pytest.mark.parametrize("body", [[], {"id": 999}, {"messages": ["secret-s2"]}])
def test_rejects_unexpected_responses(body):
    with adapter(lambda _: httpx.Response(200, json=body)) as client:
        with pytest.raises(ESPNError) as caught:
            client.league()
    assert "secret" not in str(caught.value)


def test_invalid_json():
    with adapter(lambda _: httpx.Response(200, text="<html>secret-s2</html>")) as client:
        with pytest.raises(ESPNError, match="invalid JSON"):
            client.league()


@pytest.mark.django_db
def test_sync_creates_history_and_preserves_preferences(payload):
    calls = []
    with adapter(response_handler(payload, calls)) as client:
        league, team, matchups = sync_league(client, team_id=1)
        policy = team.policy
        policy.max_weekly_adds = 4
        policy.save()
        team.preferences = {"risk": "low"}
        team.save()
        sync_league(client, team_id=1)
    assert League.objects.count() == 1
    assert FantasyTeam.objects.count() == 2
    assert Player.objects.count() == 3
    assert RosterSnapshot.objects.count() == 4
    assert FreeAgentSnapshot.objects.count() == 2
    assert AuditEvent.objects.count() == 2
    assert len(matchups) == 1
    assert MatchupSnapshot.objects.count() == 2
    slot = RosterSlot.objects.filter(player__espn_id=101).first()
    assert slot.projected_points == 19.5
    assert slot.actual_points == 0
    assert slot.injury_status == "QUESTIONABLE"
    assert league.settings["scoringSettings"]["scoringType"] == "H2H_POINTS"
    team.refresh_from_db()
    assert team.preferences == {"risk": "low"}
    assert ManagerPolicy.objects.get(team=team).max_weekly_adds == 4
    assert not team.policy.autopilot_enabled
    assert team.policy.shadow_mode
    assert len(calls) == 6


@pytest.mark.django_db
def test_missing_team_does_not_save(payload):
    with adapter(response_handler(payload, [])) as client:
        with pytest.raises(ESPNError, match="not in this league"):
            sync_league(client, team_id=999)
    assert not League.objects.exists()


@pytest.mark.django_db
def test_malformed_roster_rolls_back_entire_sync(payload):
    del payload["teams"][1]["roster"]["entries"][0]["playerPoolEntry"]["player"]["fullName"]
    with adapter(response_handler(payload, [])) as client:
        with pytest.raises(ESPNError, match="malformed"):
            sync_league(client, team_id=1)
    assert not League.objects.exists()
    assert not Player.objects.exists()


@pytest.mark.django_db
def test_failed_fetch_leaves_previous_snapshot_intact(payload):
    with adapter(response_handler(payload, [])) as client:
        sync_league(client, team_id=1)
        with patch.object(client, "free_agents", side_effect=ESPNError("unavailable")):
            with pytest.raises(ESPNError):
                sync_league(client, team_id=1)
    assert RosterSnapshot.objects.count() == 2
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_week_uses_matchup_mapping_not_week_number(payload):
    payload["settings"]["scheduleSettings"]["matchupPeriods"] = {"1": [1, 2]}
    with adapter(response_handler(payload, [])) as client:
        league, _, matchups = sync_league(client, team_id=1, week=2)
    assert league.scoring_period == 2
    assert league.matchup_period == 1
    assert len(matchups) == 1
    assert RosterSlot.objects.first().projected_points is None


@pytest.mark.django_db
def test_missing_roster_is_not_saved_as_empty(payload):
    del payload["teams"][0]["roster"]
    with adapter(response_handler(payload, [])) as client:
        with pytest.raises(ESPNError, match="missing a roster"):
            sync_league(client, team_id=1)
    assert not League.objects.exists()


@pytest.mark.django_db
def test_command_report_and_auth_only(payload, settings):
    settings.ESPN_LEAGUE_ID = 123
    settings.ESPN_TEAM_ID = 1
    settings.ESPN_SEASON = 2026
    module = "leagues.management.commands.sync_espn_league.ESPNClient"
    out = StringIO()
    with patch(module, return_value=adapter(response_handler(payload, []))):
        call_command("sync_espn_league", check_auth=True, stdout=out)
    assert "access OK" in out.getvalue()
    assert not League.objects.exists()
    out = StringIO()
    with patch(module, return_value=adapter(response_handler(payload, []))):
        call_command("sync_espn_league", stdout=out)
    assert "Example League" in out.getvalue()
    assert "19.50" in out.getvalue()
    assert "secret" not in out.getvalue()


@pytest.mark.django_db
def test_snapshot_injury_remains_historical(payload):
    with adapter(response_handler(payload, [])) as client:
        sync_league(client, team_id=1)
    newer = copy.deepcopy(payload)
    newer["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]["injuryStatus"] = (
        "ACTIVE"
    )
    with adapter(response_handler(newer, [])) as client:
        sync_league(client, team_id=1)
    assert Player.objects.get(espn_id=101).injury_status == "ACTIVE"
    assert (
        RosterSlot.objects.filter(player__espn_id=101).order_by("pk").first().injury_status
        == "QUESTIONABLE"
    )
