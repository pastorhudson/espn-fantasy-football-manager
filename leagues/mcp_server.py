"""Read-only MCP tools for discussing saved ESPN league data with ChatGPT."""

from urllib.parse import urlparse

from asgiref.sync import sync_to_async
from django.conf import settings
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .matchups import matchups_data, my_matchup_data, schedule_data
from .mcp_auth import DjangoOAuthProvider
from .mcp_data import (
    league_rosters_data,
    league_teams_data,
    manager_roster_data,
    player_projections_data,
)
from .models import TradeOffer
from .nfl_schedule import nfl_schedule_data, player_schedule_data
from .trades import list_offer_evidence, offer_evidence
from .transactions import league_transactions_data

provider = DjangoOAuthProvider()
public_url = urlparse(settings.PUBLIC_BASE_URL)
mcp = FastMCP(
    "Fantasy Football Manager",
    instructions=("Read saved ESPN matchups, schedules, starting lineups, transactions, and trade offers. State "
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


@read_only_tool("Get my matchup", "Get the manager's opponent and both saved starting lineups for a scoring week. Defaults to the latest synced week; missing lineups are explicit.")
async def get_my_matchup(week: int | None = None) -> dict:
    return await sync_to_async(my_matchup_data)(week)


@read_only_tool("Get league matchups", "Get all matchups and saved starting lineups for a scoring week. Scores are matchup-period totals, which may span several weeks.")
async def get_league_matchups(week: int | None = None) -> dict:
    return await sync_to_async(matchups_data)(week)


@read_only_tool("Get league schedule", "Get the saved season schedule, optionally filtered by ESPN team ID. Open sides may be byes or undecided opponents. Future schedules may change.")
async def get_league_schedule(team_id: int | None = None) -> dict:
    return await sync_to_async(schedule_data)(team_id)


@read_only_tool(
    "Get league transactions",
    "Get saved pickups, drops, and trades, newest first, with player names, sending and receiving "
    "teams, ESPN status, and timestamps. Optional ESPN team/player IDs filter whole transactions. "
    "Limit is 1–200. History covers saved sync observations; pending offers use list_trade_offers.",
)
async def get_league_transactions(
    team_id: int | None = None, player_id: int | None = None, limit: int = 50,
) -> dict:
    return await sync_to_async(league_transactions_data)(team_id, player_id, limit)


@mcp.tool(title="Get NFL game schedule",
          description="Fetch live ESPN regular-season NFL games, kickoff times, opponents, and status. "
          "Week 1–18 defaults to the saved league week. Time zone uses an IANA name.",
          annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def get_nfl_schedule(week: int | None = None, timezone_name: str = "America/New_York") -> dict:
    return await sync_to_async(nfl_schedule_data)(week, timezone_name)


@mcp.tool(title="Get player schedules and decision times",
          description="Find my first/next kickoff and each roster player's live ESPN game and suggested "
          "injury-review time. Includes bench alternatives. Uses latest saved roster; actual lineup locks "
          "and availability must be confirmed in ESPN. Optional fantasy team ID and player ID filter "
          "the results; week is NFL regular-season week 1–18, defaulting to saved league week.",
          annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def get_player_schedule(week: int | None = None, team_id: int | None = None,
                              player_id: int | None = None,
                              timezone_name: str = "America/New_York") -> dict:
    return await sync_to_async(player_schedule_data)(week, team_id, player_id, timezone_name)
