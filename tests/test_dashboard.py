from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from tests.test_mcp_data import league_data  # noqa: F401

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures('league_data')]


@pytest.mark.parametrize('route', ['overview', 'my-team', 'activity', 'more', 'player-schedule'])
def test_private_pages_require_access(client, django_user_model, route):
    assert client.get(reverse(route)).status_code == 302
    user = django_user_model.objects.create_user(username='reader')
    client.force_login(user)
    assert client.get(reverse(route)).status_code == 403


def test_saved_roster_renders_without_network(client, admin_user):
    client.force_login(admin_user)
    with patch('leagues.dashboard.player_schedule_data') as live:
        response = client.get(reverse('my-team'))
        assert response.status_code == 200
        assert 'Player 101' in response.content.decode()
        assert 'Player 102' not in response.content.decode()
        assert 'Player 101' not in client.get(reverse('my-team') + '?group=bench').content.decode()
        assert client.get(reverse('overview')).status_code == 200
        live.assert_not_called()


def test_live_failure_keeps_roster_and_permissioned_access(client, django_user_model):
    user = django_user_model.objects.create_user(username='reader')
    user.user_permissions.add(Permission.objects.get(codename='view_decision'))
    client.force_login(user)
    with patch('leagues.nfl_schedule.httpx.get', side_effect=__import__('httpx').ConnectError('offline')):
        response = client.get(reverse('player-schedule'))
    assert response.status_code == 200
    assert 'Player 101' in response.content.decode()
    assert 'Live kickoff times unavailable' in response.content.decode()
    assert client.get(reverse('activity') + '?team=bad').status_code == 400
