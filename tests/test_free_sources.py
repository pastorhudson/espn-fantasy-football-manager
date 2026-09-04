from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from django.utils import timezone

from decisions.lineup import recommend_lineup
from decisions.models import SourceCache
from decisions.sources.client import SourceError, cached_feed, fetch_json
from decisions.sources.free import collect_context, game_context, parse_players, parse_schedule
from leagues.models import FantasyTeam, FreeAgentSnapshot, League, RosterSlot, RosterSnapshot
from players.models import Player
from roster_actions.models import RosterAction

pytestmark = pytest.mark.django_db


@pytest.fixture
def snapshot(settings):
    settings.FREE_DATA_ENABLED = True
    league = League.objects.create(
        espn_id=1, season=2026, name="League", scoring_period=1,
        settings={"rosterSettings": {"lineupSlotCounts": {"2": 1, "20": 1}}},
    )
    team = FantasyTeam.objects.create(league=league, espn_id=1, name="Team")
    snapshot = RosterSnapshot.objects.create(team=team, scoring_period=1)
    for pid, slot, points in [(1, 2, 10), (2, 20, 20)]:
        player = Player.objects.create(espn_id=pid, name=f"Player {pid}", position_id=2)
        RosterSlot.objects.create(
            snapshot=snapshot, player=player, pro_team_id=pid, lineup_slot_id=slot,
            projected_points=points, eligible_slots=[2, 20],
        )
    FreeAgentSnapshot.objects.create(
        league=league, scoring_period=1, limit=100,
        data=[{"status": "WAIVERS", "player": {"id": 3, "fullName": "Available Player"}}],
    )
    return snapshot


@pytest.fixture
def feeds():
    future = (timezone.now() + timedelta(days=1)).timestamp() * 1000
    schedule = {"settings": {"proTeams": [
        {"id": tid, "byeWeek": 8, "abbrev": f"T{tid}", "proGamesByScoringPeriod": {
            "1": [{"id": tid, "date": future, "validForLocking": True, "startTimeTBD": False}]
        }} for tid in (1, 2)
    ]}}
    players = {
        str(pid): {"espn_id": pid, "full_name": f"Player {pid}",
                   "injury_status": "Questionable" if pid == 1 else None,
                   "practice_participation": "Limited"} for pid in (1, 2, 3)
    }
    trends = [{"player_id": "3", "count": 200}, {"player_id": "2", "count": 100}]

    def fetch(url):
        if "proTeamSchedules" in url:
            return schedule
        if "trending" in url:
            return trends
        return players
    return schedule, players, trends, fetch


def test_enrichment_cached_and_saved_immutably(snapshot, feeds, client, admin_user):
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]) as get:
        decision = recommend_lineup(snapshot)
        assert get.call_count == 3
        assert recommend_lineup(snapshot).pk == decision.pk
        collect_context(snapshot)
        assert get.call_count == 3
    result = decision.recommendation
    assert result["status"] == "review" and result["projected_total"] == 20
    assert result["evaluator_version"] == "lineup-v2"
    evidence = result["evidence"]
    assert evidence["waiver_trends"] == [
        {"player_id": 3, "name": "Available Player", "adds": 200, "status": "WAIVERS"}
    ]
    assert evidence["players"][0]["practice"] == "Limited"
    assert not RosterAction.objects.exists()
    SourceCache.objects.all().delete()
    decision.refresh_from_db()
    assert decision.recommendation["evidence"] == evidence
    client.force_login(admin_user)
    response = client.get(f"/decisions/{decision.pk}/")
    assert response.status_code == 200
    assert "Source evidence" in response.content.decode()
    assert "Available Player" in response.content.decode()


def test_bye_exclusion(snapshot, feeds):
    team = feeds[0]["settings"]["proTeams"][1]
    team["byeWeek"] = 1
    team["proGamesByScoringPeriod"] = {}
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        result = recommend_lineup(snapshot).recommendation
    assert result["projected_total"] == 10
    assert any("confirmed schedule bye" in warning for warning in result["warnings"])


@pytest.mark.parametrize("problem", ["missing", "started", "tbd", "conflict", "old_snapshot_team"])
def test_schedule_safety_blocks(snapshot, feeds, problem):
    team = feeds[0]["settings"]["proTeams"][1]
    game = team["proGamesByScoringPeriod"]["1"][0]
    if problem == "missing":
        team["proGamesByScoringPeriod"] = {}
    elif problem == "started":
        game["date"] = (timezone.now() - timedelta(minutes=1)).timestamp() * 1000
    elif problem == "tbd":
        game["startTimeTBD"] = True
    elif problem == "conflict":
        team["byeWeek"] = 1
    else:
        snapshot.slots.update(pro_team_id=None)
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        assert recommend_lineup(snapshot).recommendation["status"] == "blocked"


def test_source_failure_is_recorded_and_stale_cache_not_used(snapshot, feeds):
    SourceCache.objects.create(
        key="espn-schedule-2026", fetched_at=timezone.now() - timedelta(hours=2),
        data=parse_schedule(feeds[0]),
    )
    with patch("decisions.sources.client.fetch_json", side_effect=SourceError("Unavailable")):
        result = recommend_lineup(snapshot).recommendation
    assert result["status"] == "blocked"
    assert all(s["status"] == "unavailable" for s in result["evidence"]["sources"])


def test_optional_sleeper_failure_does_not_block(snapshot, feeds):
    def fetch(url):
        if "sleeper" in url:
            raise SourceError("Unavailable")
        return feeds[3](url)
    with patch("decisions.sources.client.fetch_json", side_effect=fetch):
        result = recommend_lineup(snapshot).recommendation
    assert result["status"] == "review"
    assert result["evidence"]["waiver_trends"] == []


def test_ambiguous_mapping_not_used(snapshot, feeds):
    feeds[1]["duplicate"] = feeds[1]["3"]
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        assert collect_context(snapshot)["waiver_trends"] == []


def test_snapshot_team_not_mutable_player_team(snapshot, feeds):
    Player.objects.all().update(pro_team_id=99)
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        assert recommend_lineup(snapshot).recommendation["status"] == "review"


def test_malformed_feed_does_not_poison_cache():
    with patch("decisions.sources.client.fetch_json", return_value=[]):
        with pytest.raises(SourceError):
            cached_feed("test", "https://example.com", 15, parse_players)
    assert not SourceCache.objects.exists()


@pytest.mark.parametrize("status,attempts", [(403, 1), (302, 1), (429, 3), (503, 3)])
def test_public_http_failures_are_sanitized(status, attempts):
    with (
        patch("decisions.sources.client.httpx.Client") as client,
        patch("decisions.sources.client.time.sleep"),
    ):
        get = client.return_value.__enter__.return_value.get
        get.return_value = httpx.Response(status, text="private-response-text")
        with pytest.raises(SourceError) as caught:
            fetch_json("https://example.com")
        assert "private" not in str(caught.value)
        assert get.call_count == attempts


def test_missing_game_is_not_bye():
    assert game_context({"bye_week": 8, "games": {}}, 1, timezone.now())["state"] == "unknown"


@pytest.mark.parametrize("placeholder", ["NA", "N/A", " na ", ""])
def test_sleeper_placeholders_do_not_create_injury_warnings(snapshot, feeds, placeholder):
    # The normalization must also apply to already-parsed, day-long cached feeds.
    players = parse_players(feeds[1])
    players["1"]["injury_status"] = placeholder
    players["1"]["practice"] = placeholder
    SourceCache.objects.create(key="sleeper-players", fetched_at=timezone.now(), data=players)
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        evidence = collect_context(snapshot)
    player = evidence["players"][0]
    assert player["mapping"] == "matched"
    assert player["sleeper_injury"] is None
    assert player["practice"] is None
    assert not any("Sleeper reports" in warning for warning in evidence["warnings"])


@pytest.mark.parametrize("reason", ["missing_id", "ambiguous", "defense"])
def test_mapping_explanations(snapshot, feeds, reason):
    if reason == "missing_id":
        feeds[1]["1"]["espn_id"] = None
        expected = "No matching ESPN ID in Sleeper data"
    elif reason == "ambiguous":
        feeds[1]["duplicate"] = feeds[1]["1"]
        expected = "Multiple Sleeper players share this ESPN ID"
    else:
        Player.objects.filter(espn_id=1).update(espn_id=-7)
        expected = "Team defense; no individual injury report"
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        evidence = collect_context(snapshot)
    assert evidence["players"][0]["mapping_note"] == expected
    assert evidence["players"][0]["sleeper_id"] is None


def test_crosswalk_fills_only_missing_sleeper_espn_ids(snapshot, feeds, settings):
    settings.PLAYER_ID_CROSSWALK_ENABLED = True
    feeds[1]["1"]["espn_id"] = None
    crosswalk = "sleeper_id,espn_id,name\n1,1,Player 1\n2,999,Wrong override\n"
    with (
        patch("decisions.sources.client.fetch_json", side_effect=feeds[3]),
        patch("decisions.sources.free.fetch_csv", return_value=crosswalk),
    ):
        evidence = collect_context(snapshot)
    first, second = evidence["players"]
    assert first["sleeper_id"] == "1"
    assert first["mapping_source"] == "DynastyProcess player IDs"
    assert second["sleeper_id"] == "2"
    assert second["mapping_source"] == "Sleeper players"
    assert evidence["sources"][2]["name"] == "DynastyProcess player IDs"


def test_crosswalk_rejects_conflicting_pairs(snapshot, feeds, settings):
    settings.PLAYER_ID_CROSSWALK_ENABLED = True
    feeds[1]["1"]["espn_id"] = None
    crosswalk = "sleeper_id,espn_id\n1,1\n1,2\n"
    with (
        patch("decisions.sources.client.fetch_json", side_effect=feeds[3]),
        patch("decisions.sources.free.fetch_csv", return_value=crosswalk),
    ):
        evidence = collect_context(snapshot)
    assert evidence["players"][0]["mapping"] == "unmapped"


def test_mapping_coverage_excludes_team_defenses(snapshot, feeds):
    Player.objects.filter(espn_id=1).update(espn_id=-7)
    with patch("decisions.sources.client.fetch_json", side_effect=feeds[3]):
        coverage = collect_context(snapshot)["mapping_coverage"]
    assert coverage == {"matched": 1, "eligible": 1, "unresolved": 0}
