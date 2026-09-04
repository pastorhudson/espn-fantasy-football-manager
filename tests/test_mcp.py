import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from starlette.testclient import TestClient

from config.asgi import application
from leagues.mcp_auth import DjangoOAuthProvider, approve_request, token_hash
from leagues.mcp_server import mcp
from leagues.models import McpOAuthClient, McpOAuthGrant


def test_mcp_advertises_league_tools():
    tools = async_to_sync(mcp.list_tools)()
    assert {tool.name for tool in tools} == {
        'get_league_rosters',
        'get_my_roster',
        'get_trade_offer',
        'list_league_teams',
        'list_player_projections',
        'list_trade_offers',
    }


@pytest.mark.django_db(transaction=True)
def test_mcp_discovery_authentication_and_tool_listing(admin_user):
    oauth_client = McpOAuthClient.objects.create(
        client_id='transport-test',
        metadata={
            'client_id': 'transport-test',
            'redirect_uris': ['https://chatgpt.com/aip/callback'],
            'token_endpoint_auth_method': 'none',
        },
    )
    token = 'transport-access-token'
    McpOAuthGrant.objects.create(
        token_hash=token_hash(token),
        kind='access',
        client=oauth_client,
        user=admin_user,
        scopes=['league:read'],
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    with TestClient(application, base_url='http://localhost:8000') as client:
        auth = client.get('/.well-known/oauth-authorization-server').json()
        resource = client.get('/.well-known/oauth-protected-resource/mcp').json()
        assert auth['code_challenge_methods_supported'] == ['S256']
        assert auth['scopes_supported'] == ['league:read']
        assert resource['resource'].endswith('/mcp')
        response = client.post('/mcp', json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-03-26', 'capabilities': {},
                       'clientInfo': {'name': 'test', 'version': '1'}},
        })
        assert response.status_code == 401
        assert 'resource_metadata=' in response.headers['www-authenticate']
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json, text/event-stream',
        }
        initialized = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {
                'protocolVersion': '2025-03-26',
                'capabilities': {},
                'clientInfo': {'name': 'transport-test', 'version': '1'},
            },
        })
        assert initialized.status_code == 200
        listed = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {},
        })
        assert listed.status_code == 200
        assert {tool['name'] for tool in listed.json()['result']['tools']} == {
            'get_league_rosters',
            'get_my_roster',
            'get_trade_offer',
            'list_league_teams',
            'list_player_projections',
            'list_trade_offers',
        }


@pytest.mark.django_db(transaction=True)
def test_oauth_authorization_code_flow(admin_user):
    provider = DjangoOAuthProvider()
    client = OAuthClientInformationFull(
        client_id='chatgpt-test', client_secret='secret',
        redirect_uris=['https://chatgpt.com/aip/callback'],
        token_endpoint_auth_method='client_secret_post', scope='league:read',
    )
    async_to_sync(provider.register_client)(client)
    params = AuthorizationParams(
        state='state-1', scopes=['league:read'], code_challenge='challenge',
        redirect_uri='https://chatgpt.com/aip/callback',
        redirect_uri_provided_explicitly=True, resource='http://localhost:8000/mcp',
    )
    authorize_url = async_to_sync(provider.authorize)(client, params)
    request_token = parse_qs(urlparse(authorize_url).query)['request'][0]
    callback = approve_request(request_token, admin_user)
    query = parse_qs(urlparse(callback).query)
    assert query['state'] == ['state-1']
    code = async_to_sync(provider.load_authorization_code)(client, query['code'][0])
    token = async_to_sync(provider.exchange_authorization_code)(client, code)
    access = async_to_sync(provider.load_access_token)(token.access_token)
    assert access.subject == str(admin_user.pk)
    assert access.scopes == ['league:read']
    assert access.expires_at > time.time()
