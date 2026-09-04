"""Read-only adapter for ESPN's unofficial fantasy API (2019+ seasons)."""

import json
import time

import httpx


class ESPNError(Exception):
    """Safe to display: never contains response bodies, cookies or request headers."""


class ESPNAuthenticationError(ESPNError):
    pass


class ESPNClient:
    def __init__(self, league_id, season, *, espn_s2="", swid="", transport=None, sleep=time.sleep):
        if league_id <= 0 or season < 2019:
            raise ESPNError("Set a positive ESPN_LEAGUE_ID and ESPN_SEASON of 2019 or later.")
        if bool(espn_s2) != bool(swid):
            raise ESPNAuthenticationError("Private leagues require both ESPN_S2 and ESPN_SWID.")
        self.league_id = league_id
        self.season = season
        self._sleep = sleep
        self._url = (
            "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/"
            f"seasons/{season}/segments/0/leagues/{league_id}"
        )
        self._http = httpx.Client(
            cookies={"espn_s2": espn_s2, "SWID": swid} if espn_s2 else {},
            timeout=httpx.Timeout(20, connect=5),
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()

    def _get(self, views, *, week=None, filters=None):
        params = [("view", view) for view in views]
        if week is not None:
            if week < 0:
                raise ESPNError("Scoring period must be nonnegative.")
            params.append(("scoringPeriodId", week))
        headers = {"x-fantasy-filter": json.dumps(filters)} if filters else {}
        for attempt in range(3):
            try:
                response = self._http.get(self._url, params=params, headers=headers)
            except httpx.TransportError:
                if attempt == 2:
                    raise ESPNError("Could not reach ESPN after three attempts.") from None
                self._sleep(2**attempt)
                continue
            if response.status_code in (401, 403) or response.is_redirect:
                raise ESPNAuthenticationError(
                    "ESPN access denied. Check league access or refresh ESPN_S2 and ESPN_SWID."
                )
            if response.status_code == 404:
                raise ESPNError("ESPN league/season was not found.")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = min(int(retry_after), 30) if retry_after.isdigit() else 2**attempt
                    self._sleep(delay)
                    continue
                raise ESPNError(f"ESPN is temporarily unavailable (HTTP {response.status_code}).")
            if response.status_code != 200:
                raise ESPNError(
                    f"ESPN request failed (HTTP {response.status_code}; "
                    f"views={','.join(views)}; scoring_period={week})."
                )
            try:
                data = response.json()
            except ValueError:
                raise ESPNError(
                    "ESPN returned an invalid JSON response; check access credentials."
                ) from None
            if not isinstance(data, dict) or data.get("messages") or data.get("error"):
                raise ESPNError("ESPN returned an unexpected response.")
            return data
        raise ESPNError("ESPN request failed.")

    def league(self, *, week=None):
        data = self._get(["mSettings", "mTeam", "mRoster", "mMatchup", "mStatus"], week=week)
        if data.get("id") != self.league_id or data.get("seasonId") != self.season:
            raise ESPNError("ESPN returned a different league or season.")
        if not isinstance(data.get("settings"), dict) or not isinstance(data.get("teams"), list):
            raise ESPNError("ESPN league response is missing settings or teams.")
        return data

    def check_authentication(self):
        """Checks league access; public league access does not validate an account cookie."""
        self.league()
        return True

    def free_agents(self, *, week, limit=100):
        if not 1 <= limit <= 1000:
            raise ESPNError("Free-agent limit must be between 1 and 1000.")
        data = self._get(
            ["kona_player_info"],
            week=week,
            filters={
                "players": {
                    "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                    "limit": limit,
                    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                }
            },
        )
        if not isinstance(data.get("players"), list):
            raise ESPNError("ESPN free-agent response is missing players.")
        return data["players"][:limit]

    def transactions(self, *, week):
        data = self._get(
            ["mTransactions2"],
            week=week,
            filters={
                "transactions": {
                    "filterType": {"value": ["FREEAGENT", "WAIVER", "TRADE_ACCEPT", "ROSTER"]}
                }
            },
        )
        # ESPN may omit this field when there are no visible transactions.
        result = data.get("transactions", [])
        if not isinstance(result, list):
            raise ESPNError("ESPN returned invalid transaction data.")
        return result

    def pending_transactions(self, *, week):
        data = self._get(["mPendingTransactions"], week=week)
        result = data.get("pendingTransactions", [])
        if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise ESPNError("ESPN returned invalid pending trade data.")
        return [row for row in result if row.get("type") in {"TRADE", "TRADE_PROPOSAL"}]
