from datetime import UTC, datetime
from unittest.mock import Mock, patch

import httpx
import pytest

from leagues.nfl_schedule import nfl_schedule_data, player_schedule_data
from tests.test_mcp_data import league_data  # noqa: F401

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("league_data")]


def scoreboard():
    return {'season': {'year': 2026, 'type': 2}, 'week': {'number': 1}, 'events': [{
        'id': 'game', 'name': 'One at Two', 'competitions': [{
            'date': '2026-09-13T17:00Z', 'timeValid': True,
            'status': {'type': {'name': 'STATUS_SCHEDULED', 'state': 'pre'}},
            'competitors': [
                {'team': {'id': '1', 'displayName': 'One'}, 'homeAway': 'away'},
                {'team': {'id': '2', 'displayName': 'Two'}, 'homeAway': 'home'},
            ],
        }],
    }]}


def test_live_schedule_and_roster_deadlines():
    with patch('leagues.nfl_schedule.httpx.get', return_value=Mock(json=scoreboard)), patch(
        'leagues.nfl_schedule.timezone.now', return_value=datetime(2026, 9, 5, tzinfo=UTC)
    ):
        result = player_schedule_data()
    assert result['available']
    assert result['first_kickoff'] == '2026-09-13T13:00:00-04:00'
    assert result['next_kickoff'] == result['first_kickoff']
    assert result['players'][0]['suggested_review_at'] == '2026-09-13T11:30:00-04:00'
    assert result['players'][0]['kickoff_has_passed'] is False
    assert result['players'][0]['games'][0]['teams'][1]['name'] == 'Two'


def test_unknown_time_and_failed_fetch():
    data = scoreboard()
    data['events'][0]['competitions'][0]['timeValid'] = False
    with patch('leagues.nfl_schedule.httpx.get', return_value=Mock(json=lambda: data)):
        result = player_schedule_data()
    assert result['first_kickoff'] is None
    assert result['players'][0]['suggested_review_at'] is None
    with patch('leagues.nfl_schedule.httpx.get', side_effect=httpx.ConnectError('offline')):
        result = player_schedule_data()
    assert not result['available']
    assert result['players'][0]['schedule_status'] == 'unknown'


def test_wrong_week_filters_and_past_kickoff():
    with patch('leagues.nfl_schedule.httpx.get', return_value=Mock(json=scoreboard)), patch(
        'leagues.nfl_schedule.timezone.now', return_value=datetime(2026, 9, 14, tzinfo=UTC)
    ):
        assert not nfl_schedule_data(2)['available']
        assert player_schedule_data(player_id=999)['players'] == []
        result = player_schedule_data(team_id=2, player_id=102)
        assert result['players'][0]['kickoff_has_passed']
        assert result['next_kickoff'] is None
    with pytest.raises(ValueError):
        nfl_schedule_data(19)
    with pytest.raises(ValueError):
        nfl_schedule_data(1, 'not-a-timezone')
