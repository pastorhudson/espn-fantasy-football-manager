import pytest

from leagues.mcp_data import (
    league_rosters_data,
    league_teams_data,
    manager_roster_data,
    player_projections_data,
)
from leagues.models import FantasyTeam, FreeAgentSnapshot, League, RosterSlot, RosterSnapshot
from players.models import Player

pytestmark = pytest.mark.django_db


@pytest.fixture
def league_data(settings):
    settings.ESPN_LEAGUE_ID = 123
    settings.ESPN_TEAM_ID = 1
    settings.ESPN_SEASON = 2026
    league = League.objects.create(
        espn_id=123, season=2026, name='Test League', scoring_period=1
    )
    for team_id, team_name, player_id, projection in (
        (1, 'My Team', 101, 12.5),
        (2, 'Other Team', 102, None),
    ):
        team = FantasyTeam.objects.create(
            league=league, espn_id=team_id, name=team_name, waiver_rank=team_id
        )
        snapshot = RosterSnapshot.objects.create(team=team, scoring_period=1)
        player = Player.objects.create(
            espn_id=player_id, name=f'Player {player_id}', position_id=2
        )
        RosterSlot.objects.create(
            snapshot=snapshot,
            player=player,
            lineup_slot_id=2,
            projected_points=projection,
            eligible_slots=[2, 20],
            pro_team_id=team_id,
        )
    FreeAgentSnapshot.objects.create(
        league=league,
        scoring_period=1,
        limit=50,
        data=[{
            'status': 'FREEAGENT',
            'player': {
                'id': 103,
                'fullName': 'Free Agent',
                'defaultPositionId': 4,
                'eligibleSlots': [4, 20],
                'proTeamId': 3,
                'stats': [{
                    'seasonId': 2026,
                    'scoringPeriodId': 1,
                    'statSourceId': 1,
                    'statSplitTypeId': 1,
                    'appliedTotal': 9.75,
                }],
            },
        }],
    )
    return league


def test_roster_and_team_payloads(league_data):
    mine = manager_roster_data()
    teams = league_teams_data()
    rosters = league_rosters_data()

    assert mine['roster']['team_name'] == 'My Team'
    assert mine['roster']['players'][0]['projected_points'] == 12.5
    assert teams['count'] == 2
    assert {team['roster_size'] for team in teams['teams']} == {1}
    assert rosters['count'] == 2
    assert sum(len(roster['players']) for roster in rosters['rosters']) == 2


def test_projection_payload_includes_rosters_and_bounded_free_agents(league_data):
    result = player_projections_data()

    assert {player['player_id'] for player in result['players']} == {101, 102, 103}
    free_agent = next(player for player in result['players'] if player['player_id'] == 103)
    assert free_agent['projected_points'] == 9.75
    assert result['coverage'] == {
        'total': 3,
        'with_projection': 2,
        'rostered': 2,
        'free_agent_sample_limit': 50,
        'is_full_espn_player_universe': False,
    }
