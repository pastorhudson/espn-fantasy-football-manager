import pytest

from leagues.matchups import matchups_data, my_matchup_data, schedule_data
from leagues.models import MatchupSnapshot, RosterSnapshot
from tests.test_mcp_data import league_data  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def scheduled(league_data):  # noqa: F811 — imported pytest fixture
    league_data.matchup_period = 1
    league_data.settings = {"scheduleSettings": {"matchupPeriods": {"1": [1, 2], "2": [3]}}}
    league_data.schedule = [
        {"id": 1, "matchupPeriodId": 1, "home": {"teamId": 2, "totalPoints": 0},
         "away": {"teamId": 1, "totalPoints": 5}},
        {"id": 2, "matchupPeriodId": 2, "home": {"teamId": 1}},
    ]
    league_data.save()
    return league_data


def test_opponent_lineups_and_schedule(scheduled):
    result = my_matchup_data()
    matchup = result["matchups"][0]
    assert matchup["home"]["team_name"] == "Other Team"
    assert matchup["away"]["is_manager_team"]
    assert matchup["home"]["total_points"] == 0
    assert matchup["away"]["projected_starter_total"] == 12.5
    assert matchup["home"]["projected_starter_total"] is None
    assert schedule_data()["count"] == 2
    assert schedule_data(2)["count"] == 1
    assert matchups_data(2)["count"] == 1
    assert not matchups_data(2)["matchups"][0]["away"]["lineup_available"]
    assert matchups_data(3)["matchups"][0]["has_open_side"]
    assert matchups_data(99)["count"] == 0


def test_bench_excluded_and_wrong_week_not_used(scheduled):
    team = scheduled.teams.get(espn_id=1)
    snapshot = team.roster_snapshots.first()
    snapshot.slots.update(lineup_slot_id=20)
    RosterSnapshot.objects.create(team=team, scoring_period=9)
    side = my_matchup_data()["matchups"][0]["away"]
    assert side["lineup_available"]
    assert side["starters"] == []
    assert side["projected_starter_total"] is None


def test_legacy_dedup_and_empty_schedule(scheduled):
    for score in (1, 2):
        MatchupSnapshot.objects.create(
            league=scheduled, espn_id=1, scoring_period=1, matchup_period=1,
            data={"id": 1, "matchupPeriodId": 1, "home": {"teamId": 1, "totalPoints": score}},
        )
    scheduled.schedule = None
    scheduled.save()
    assert not schedule_data()["full_schedule_saved"]
    assert schedule_data()["count"] == 1
    assert schedule_data()["matchups"][0]["home"]["total_points"] == 2
    scheduled.schedule = []
    scheduled.save()
    assert schedule_data()["count"] == 0


def test_empty_database():
    assert my_matchup_data()["count"] == 0


def test_view_permissions_and_render(client, admin_client, django_user_model, scheduled):
    assert client.get("/matchups/").status_code == 302
    user = django_user_model.objects.create_user(username="viewer", password="pass")
    client.force_login(user)
    assert client.get("/matchups/").status_code == 403
    response = admin_client.get("/matchups/")
    assert response.status_code == 200
    assert b"Other Team" in response.content
    assert b"Player 101" in response.content
    assert b"Season schedule" in response.content
    assert admin_client.get("/matchups/?week=bad").status_code == 400
    assert b"No lineup saved" in admin_client.get("/matchups/?week=3").content
