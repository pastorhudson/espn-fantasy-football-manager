"""OAuth 2.1 provider for the private, read-only MCP endpoint."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .models import McpOAuthClient, McpOAuthGrant


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class DjangoOAuthProvider:
    async def get_client(self, client_id):
        row = await McpOAuthClient.objects.filter(client_id=client_id).afirst()
        return OAuthClientInformationFull.model_validate(row.metadata) if row else None

    async def register_client(self, client_info):
        await McpOAuthClient.objects.aupdate_or_create(
            client_id=client_info.client_id,
            defaults={"metadata": client_info.model_dump(mode="json")},
        )

    async def authorize(self, client, params: AuthorizationParams):
        request_token = secrets.token_urlsafe(32)
        await McpOAuthGrant.objects.acreate(
            token_hash=token_hash(request_token), kind="request",
            client_id=client.client_id, scopes=params.scopes or ["league:read"],
            expires_at=timezone.now() + timedelta(minutes=10),
            data=params.model_dump(mode="json"),
        )
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}{reverse('mcp-authorize')}?request={request_token}"

    async def load_authorization_code(self, client, authorization_code):
        row = await self._grant(authorization_code, "code", client.client_id)
        if not row:
            return None
        return AuthorizationCode(
            code=authorization_code, scopes=row.scopes,
            expires_at=row.expires_at.timestamp(), client_id=client.client_id,
            subject=str(row.user_id), **row.data,
        )

    async def exchange_authorization_code(self, client, authorization_code):
        await McpOAuthGrant.objects.filter(
            token_hash=token_hash(authorization_code.code), kind="code"
        ).adelete()
        return await self._issue(client.client_id, authorization_code.scopes, authorization_code.subject)

    async def load_refresh_token(self, client, refresh_token):
        row = await self._grant(refresh_token, "refresh", client.client_id)
        return RefreshToken(
            token=refresh_token, client_id=client.client_id, scopes=row.scopes,
            expires_at=int(row.expires_at.timestamp()), subject=str(row.user_id),
        ) if row else None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        await McpOAuthGrant.objects.filter(
            token_hash=token_hash(refresh_token.token), kind="refresh"
        ).adelete()
        return await self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.subject)

    async def load_access_token(self, token):
        row = await self._grant(token, "access")
        return AccessToken(
            token=token, client_id=row.client_id, scopes=row.scopes,
            expires_at=int(row.expires_at.timestamp()), resource=settings.MCP_RESOURCE_URL,
            subject=str(row.user_id),
        ) if row else None

    async def revoke_token(self, token):
        await McpOAuthGrant.objects.filter(token_hash=token_hash(token.token)).adelete()

    async def _grant(self, token, kind, client_id=None):
        query = McpOAuthGrant.objects.filter(
            token_hash=token_hash(token), kind=kind, expires_at__gt=timezone.now()
        )
        if client_id:
            query = query.filter(client_id=client_id)
        return await query.afirst()

    async def _issue(self, client_id, scopes, subject):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        user_id = int(subject)
        now = timezone.now()
        await McpOAuthGrant.objects.abulk_create([
            McpOAuthGrant(
                token_hash=token_hash(access), kind="access", client_id=client_id,
                user_id=user_id, scopes=scopes, expires_at=now + timedelta(hours=1),
            ),
            McpOAuthGrant(
                token_hash=token_hash(refresh), kind="refresh", client_id=client_id,
                user_id=user_id, scopes=scopes, expires_at=now + timedelta(days=30),
            ),
        ])
        return OAuthToken(
            access_token=access, refresh_token=refresh, expires_in=3600,
            scope=" ".join(scopes),
        )


def approve_request(request_token, user):
    row = McpOAuthGrant.objects.select_related("client").filter(
        token_hash=token_hash(request_token), kind="request", expires_at__gt=timezone.now()
    ).first()
    if not row:
        return None
    params = row.data
    code = secrets.token_urlsafe(32)
    McpOAuthGrant.objects.create(
        token_hash=token_hash(code), kind="code", client=row.client, user=user,
        scopes=row.scopes, expires_at=timezone.now() + timedelta(minutes=5),
        data={
            "code_challenge": params["code_challenge"],
            "redirect_uri": params["redirect_uri"],
            "redirect_uri_provided_explicitly": params["redirect_uri_provided_explicitly"],
            "resource": params.get("resource"),
        },
    )
    row.delete()
    return construct_redirect_uri(params["redirect_uri"], code=code, state=params.get("state"))
