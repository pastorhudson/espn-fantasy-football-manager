"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from starlette.applications import Starlette
from starlette.routing import Mount, Route

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_application = get_asgi_application()

from leagues.mcp_server import mcp  # noqa: E402

mcp_application = mcp.streamable_http_app()
# Some MCP clients probe the origin rather than the configured /mcp path.
# Reuse SDK handlers so aliases retain OAuth enforcement and discovery metadata.
mcp_route = next(route for route in mcp_application.routes if route.path == "/mcp")
resource_route = next(
    route for route in mcp_application.routes
    if route.path == "/.well-known/oauth-protected-resource/mcp"
)
application = Starlette(
    routes=[
        *mcp_application.routes,
        Route("/.well-known/oauth-protected-resource", endpoint=resource_route.app,
              methods=["GET", "OPTIONS"]),
        Route("/", endpoint=mcp_route.app, methods=["POST"]),
        Mount("/", app=django_application),
    ],
    middleware=mcp_application.user_middleware,
    lifespan=mcp_application.router.lifespan_context,
)
