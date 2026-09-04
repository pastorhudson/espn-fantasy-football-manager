# ESPN Fantasy Football Manager

Django service for observing an ESPN fantasy league and, in later phases, proposing
roster decisions. Phases 1–4 provide environment configuration, database models,
read-only administration, ESPN synchronization, and shadow lineup recommendations.

**This release cannot change an ESPN roster.** There is no write transport or
executor. Autopilot defaults to off; shadow mode defaults to on. Environment or
policy flags cannot enable writes in this release.

## Local setup

Use Python 3.14 (the repository pin), or supported Python 3.13, and `uv`:

```bash
uv sync --all-groups
cp .env.example .env
uv run python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Put the generated value in `.env` as `SECRET_KEY`. Set `ESPN_LEAGUE_ID`,
`ESPN_TEAM_ID`, and `ESPN_SEASON` to your league, team, and season. For a private
league, set both `ESPN_S2` and `ESPN_SWID` using your ESPN account cookies. Keep
cookies in `.env` locally or deployment secrets; never commit them or paste them
into reports. A public league can be read without cookies.

```bash
uv run python manage.py migrate
uv run python manage.py sync_espn_league --check-auth
uv run python manage.py sync_espn_league
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

`--check-auth` verifies access to the configured league without writing to the
local database. Access to a public league does not prove that cookies are valid.
Use `/fantasy-backend/` to inspect models and `/health/` for a database readiness check.
All domain administration is view-only in this milestone.

The sync command prints the league, ESPN scoring type, selected roster, weekly
projections, injury status, and opponent team IDs. Full scoring rules, lineup
rules, acquisition budgets, waiver rank, and team transaction counters are stored
for later interpretation. A missing projection stays unknown rather than becoming
zero. This is an observation report, not a lineup recommendation engine.

Optional arguments:

```bash
uv run python manage.py sync_espn_league --week 1 --free-agent-limit 100
```

An explicit scoring week is mapped through the league's matchup-period settings;
a matchup period may span multiple weeks. The free-agent snapshot is a bounded
sample (default 100, maximum 1,000) including waiver players, not an exhaustive
pool. Recent transactions are limited to those ESPN exposes for the scoring
period. Missing transaction data is treated as no visible transactions.

## Data and failure behavior

League and team identities are unique within a season; player identities use
ESPN IDs, including negative IDs for team defenses. Every successful sync creates
new roster, matchup, and free-agent observations and an audit event. Repeated
syncs intentionally retain history, while keeping one league/team/player identity.
Roster slots preserve observed injury status and eligible positions alongside
points, so later player updates do not rewrite those historical observations.

All HTTP requests complete before the database transaction begins. Missing team
or roster data, invalid payloads, and failed requests abort the sync. Database
changes are atomic. Existing team preferences and manager policies survive syncs.
Manual and scheduled syncs share a database lease per league and season. Overlapping
runs are rejected; a lease expires after 15 minutes, and an expired owner cannot
persist its fetched data. Scheduled runs prune observations older than 30 days
(configurable with `SNAPSHOT_RETENTION_DAYS`). The latest roster per team, latest
free-agent sample, latest observation per matchup, decision evidence, and audit
events are retained. Decision evidence and audits therefore continue to grow.

The HTTP client uses fixed read endpoints, bounded timeouts, and at most three
attempts for transport failures, HTTP 429, and server errors. Authentication
failures and redirects are not retried. Errors omit response bodies and cookies.
Do not enable HTTP wire logging in production. Database snapshots contain league
and owner information and should be treated as private application data.

ESPN does not offer a supported public management API. Request shapes were checked
against the [espn-api implementation](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/league.py).
Fixtures in `tests/fixtures` are synthetic and contain no real account data.
Live access still needs verification with the configured league and credentials.

## Validation

Tests use isolated in-memory SQLite settings and mock HTTP; no ESPN access or
credentials are required:

```bash
uv run pytest -q
uv run ruff check .
uv run python manage.py check --settings=config.test_settings
uv run python manage.py makemigrations --check --dry-run --settings=config.test_settings
```

## Production / Dokku preparation

See [the deployment guide](docs/dokku.md) for the `fantasy` app on
`fantasy.home`, including server setup, SSH access, TLS, and deployment commands.

Set `DEBUG=false`, a random `SECRET_KEY` of at least 50 characters, explicit
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, PostgreSQL `DATABASE_URL`, and Redis
`REDIS_URL`. The application requires an explicit database URL outside debug
mode. HTTPS redirect, secure session/CSRF cookies, and HSTS default on. Enable
`TRUST_PROXY_SSL_HEADER=true` only when the trusted reverse proxy replaces the
forwarded protocol header. `/health/` follows the same HTTPS policy.
`check --deploy` reports W005/W021 until you opt into
`SECURE_HSTS_INCLUDE_SUBDOMAINS=true` and `SECURE_HSTS_PRELOAD=true`; leave those
off until the domain and all affected subdomains are ready for that commitment.

The Procfile defines Gunicorn, Celery worker, and database-backed Celery beat.
Install the opt-in schedule as described below. Run exactly one beat instance. The Dockerfile installs production dependencies from `uv.lock`. `app.json` runs
migrations and static collection before deployment, starts one web, worker, and beat process,
and checks database readiness. The web service, scheduled synchronization, and
saved shadow decisions were verified on `fantasy.marvn.app` on September 4, 2026.

```bash
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
uv run python manage.py check --deploy
```

WhiteNoise serves collected static files. Verify host/proxy configuration,
database backups, and deployment secrets against the
[Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
The old development secret has been removed from settings; never reuse it.

## Phase 4: shadow recommendations and scheduling

### Sign in and review decisions

Use `/accounts/login/` to sign in with an existing Django account (including
your admin account). The home page links to sign-in, and successful login opens
`/decisions/`. This page lists saved decisions, newest first; open a decision
to see projections, lineup positions, proposed moves, and warnings.

Superusers have access automatically. Other accounts need the Django
`decisions.view_decision` permission, which grants access to all saved decisions
in this single-manager application. There is no public account registration or
per-team account ownership. Sign-out uses a CSRF-protected POST form.

### Evaluate and schedule

After deploying and migrating, evaluate an existing snapshot:

```bash
uv run python manage.py recommend_lineup
```

This saves a `Decision` visible under Decisions in `/fantasy-backend/`, including
starter assignments, proposed slot changes, projected totals, and warnings.
Evaluation uses ESPN lineup slot counts and player eligibility, optimizing all
starter positions together (including flex). OUT, doubtful, suspended, and IR
players are excluded; players in the IR roster slot are not promoted. Missing
projections or eligibility, stale snapshots over two hours, and impossible lineups
produce a blocked decision. Zero projections and injury designations are flagged.
Free schedule enrichment checks byes and kickoff times as described below.
ESPN roster locks and confirmed inactives still require review in ESPN. These are projection comparisons, not executable plans.
Policy flags cannot turn them into ESPN writes. Re-evaluating a snapshot returns
its existing decision; sync again to get a fresh evaluation.

### Free schedule and player context

New decisions use free public ESPN NFL schedules and the documented Sleeper API
by default (`FREE_DATA_ENABLED=true`). No API key or paid subscription is needed.
ESPN remains the sole numerical projection source; no FantasyPros sample data is
used. Sleeper is supplemental context, not a second projection model.

The evaluator excludes explicit schedule byes. If any non-IR roster player's
schedule is unknown, conflicting, or already past kickoff, the decision is
blocked. This conservative behavior also applies to bench players: optimizing
around locked slots is a later milestone. A missing game is not treated as a bye.
Kickoff data does not establish ESPN roster-lock rules or confirmed inactives.

Decision details show schedule checks, Sleeper injury/practice context, source
retrieval times, and a waiver watch. Sleeper source-update times are not supplied
by this adapter, so its injury information only produces review warnings and
never overrides ESPN eligibility. Player matching uses explicit ESPN IDs; missing
or ambiguous matches are skipped. Trending adds are matched only against the
saved, bounded ESPN free-agent/waiver sample. They are not add recommendations or
a guarantee of current availability. An empty watch does not mean no free agents.

Public schedule responses are cached for 15 minutes, Sleeper players for one day,
and trending adds for one hour. Expired cache entries are not reused after a
failed refresh. Schedule failure blocks evaluation; Sleeper failure is recorded
and leaves the ESPN-based evaluation available. Requests have bounded timeouts
and retries. All source requests occur before the decision transaction and use
no private ESPN cookies. Each decision retains its source evidence and evaluator
version even when the shared cache changes.

Deploy both new migrations before starting the updated processes. Then let the
next scheduled ESPN sync create a fresh roster and decision. Existing decisions
are unchanged; older roster slots have no historical NFL team ID and need a fresh
sync for schedule checks. To disable enrichment and restore the original
projection-only behavior, set `FREE_DATA_ENABLED=false` and restart the processes.

Source references: [Sleeper API and noncommercial usage terms](https://docs.sleeper.com/),
[ESPN schedule adapter reference](https://github.com/cwendt94/espn-api/blob/master/espn_api/requests/espn_requests.py).

Enable the schedule explicitly (defaults to every 30 minutes, minimum five):

```bash
uv run python manage.py configure_sync_schedule --minutes 30
```

Each scheduled run fetches a new observation, saves a shadow decision, and prunes
old unreferenced observations. Failures record a sanitized `sync.failed` audit
entry; the next scheduled run tries again. The HTTP client retains its bounded
request retries. No notifications are sent in this phase.

For the deployed Dokku app, after pushing the code and running migrations:

```bash
dokku run fantasy python manage.py configure_sync_schedule --minutes 30
dokku ps:scale fantasy
dokku logs fantasy --tail
```

`app.json` controls process counts: deployment starts one web, worker, and beat
process. `dokku ps:scale fantasy` displays those counts; changing counts through
that command is disabled while `formation` is present. Edit `app.json` and
redeploy to change them.

Redis must be configured via `REDIS_URL`. Confirm a new `espn.sync` audit and a
`shadow_lineup` decision appear after the first interval. Disable scheduling with:

```bash
dokku run fantasy python manage.py configure_sync_schedule --disable
```

Disabling prevents future dispatches; a task already queued may finish.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for completed phases, Phase 4 verification, and
planned milestones.
