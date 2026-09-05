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


def test_transaction_history_filters_deduplication_and_names(league_data):
    from leagues.transactions import league_transactions_data
    from roster_actions.models import AuditEvent

    def movement(player, action, source, destination):
        return dict(playerId=player, type=action, fromTeamId=source, toTeamId=destination)

    trade = dict(id='trade', type='TRADE_ACCEPT', status='EXECUTED', processDate=2000,
                 items=[movement(101, 'TRADE', 1, 2), movement(102, 'TRADE', 2, 1)])
    pickup = dict(id='pickup', type='FREEAGENT', processDate=1000,
                  items=[movement(103, 'ADD', -1, 1), movement(999, 'DROP', 1, -1)])
    for rows in ([pickup, trade], [trade]):
        AuditEvent.objects.create(league=league_data, kind='espn.sync',
                                  details={'transactions': rows, 'scoring_period': 1})
    other = League.objects.create(espn_id=999, season=2026, name='Other')
    AuditEvent.objects.create(league=other, kind='espn.sync', details={'transactions': [pickup]})
    result = league_transactions_data(limit=1)
    assert result['count'] == 1
    assert result['total_matching'] == 2
    assert result['has_more'] is True
    trade_row = result['transactions'][0]
    assert trade_row['transaction_id'] == 'trade'
    assert trade_row['processed_at'] == '1970-01-01T00:00:02+00:00'
    assert trade_row['players'][0]['player_name'] == 'Player 101'
    assert trade_row['players'][0]['from_team'] == 'My Team'
    assert trade_row['players'][0]['to_team'] == 'Other Team'
    assert league_transactions_data(team_id=2)['count'] == 1
    assert len(league_transactions_data(player_id=101)['transactions'][0]['players']) == 2
    dropped = league_transactions_data(player_id=999)['transactions'][0]['players'][1]
    assert dropped['action'] == 'DROP'
    assert dropped['player_name'] == 'Unknown player'
    assert dropped['to_team'] is None
    assert league_transactions_data(team_id=999)['count'] == 0


def test_transaction_history_empty_and_limit_validation():
    from leagues.transactions import league_transactions_data

    assert league_transactions_data()['transactions'] == []
    assert league_transactions_data()['latest_observed_at'] is None
    for limit in (0, 201):
        with pytest.raises(ValueError, match='Limit'):
            league_transactions_data(limit=limit)
