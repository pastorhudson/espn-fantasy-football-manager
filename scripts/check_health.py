"""Check the live container HTTP server and database without printing secrets."""

import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

request = Request(
    f"http://127.0.0.1:{int(os.environ.get('PORT', '8000'))}/health/",
    headers={
        "Host": "localhost",
        # The check connects directly to the container, bypassing Dokku's TLS proxy.
        "X-Forwarded-Proto": "https",
    },
)
try:
    with urlopen(request, timeout=5) as response:
        healthy = response.status == 200 and json.load(response).get("status") == "ok"
except (URLError, ValueError, TimeoutError):
    healthy = False
if not healthy:
    sys.exit("Application readiness check failed.")
print("Application and database are ready.")
