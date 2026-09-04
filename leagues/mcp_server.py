"""Read-only MCP tools for discussing saved trade offers with ChatGPT."""

from asgiref.sync import sync_to_async
from django.conf import settings
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .mcp_auth import DjangoOAuthProvider
from .models import TradeOffer
from .trades import list_offer_evidence, offer_evidence

provider = DjangoOAuthProvider()
mcp = FastMCP(
    "Fantasy Football Manager",
    instructions=("Read pending ESPN trade offers and saved roster context. State "
                  "uncertainty and remind the manager to act in ESPN."),
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=settings.PUBLIC_BASE_URL,
        resource_server_url=settings.MCP_RESOURCE_URL,
        required_scopes=["trades:read"],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["trades:read"], default_scopes=["trades:read"]
        ),
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
