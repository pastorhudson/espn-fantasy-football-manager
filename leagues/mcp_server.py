"""Read-only MCP tools for discussing saved ESPN league data with ChatGPT."""

from urllib.parse import urlparse

from asgiref.sync import sync_to_async
from django.conf import settings
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .mcp_auth import DjangoOAuthProvider
from .mcp_data import (
    league_rosters_data,
    league_teams_data,
    manager_roster_data,
    player_projections_data,
)
from .models import TradeOffer
from .trades import list_offer_evidence, offer_evidence

provider = DjangoOAuthProvider()
public_url = urlparse(settings.PUBLIC_BASE_URL)
mcp = FastMCP(
    "Fantasy Football Manager",
    instructions=("Read pending ESPN trade offers and saved roster context. State "
                  "uncertainty and remind the manager to act in ESPN."),
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=settings.PUBLIC_BASE_URL,
        resource_server_url=settings.MCP_RESOURCE_URL,
        required_scopes=["league:read"],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["league:read"], default_scopes=["league:read"]
        ),
    ),
    transport_security=TransportSecuritySettings(
        allowed_hosts=[public_url.netloc, "127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[
            f"{public_url.scheme}://{public_url.netloc}",
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ],
    ),
    streamable_http_path="/mcp", stateless_http=True, json_response=True,
)


@mcp.tool(title="List trade offers",
          description="List pending ESPN trade offers with players, teams, projections, and injuries.",
          annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
async def list_trade_offers() -> dict:
    offers = await sync_to_async(list_offer_evidence)()
    return {"offers": offers, "count": len(offers)}


@mcp.tool(title="Get trade offer",
          description="Get complete saved evidence for one ESPN trade offer by its offer ID.",
          annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
async def get_trade_offer(offer_id: str) -> dict:
    def get():
        offer = TradeOffer.objects.select_related("league", "proposing_team").filter(
            espn_id=offer_id
        ).first()
        return offer_evidence(offer) if offer else None
    offer = await sync_to_async(get)()
    return {"offer": offer, "found": offer is not None}


def read_only_tool(title, description):
    return mcp.tool(
        title=title, description=description,
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )


@read_only_tool("Get my roster", "Get the manager's latest roster, lineup slots, projections, and injuries.")
async def get_my_roster() -> dict:
    return await sync_to_async(manager_roster_data)()


@read_only_tool("List league teams", "List every team in the configured ESPN league.")
async def list_league_teams() -> dict:
    return await sync_to_async(league_teams_data)()


@read_only_tool("Get league rosters", "Get the latest saved roster for every team in the ESPN league.")
async def get_league_rosters() -> dict:
    return await sync_to_async(league_rosters_data)()


@read_only_tool(
    "List player projections",
    "List all ESPN projections available in the latest league rosters and bounded free-agent sample.",
)
async def list_player_projections() -> dict:
    return await sync_to_async(player_projections_data)()
