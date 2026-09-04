# ESPN Fantasy Football Manager

Django service for observing an ESPN fantasy league and, in later phases, proposing
roster decisions. Phases 1–3 provide environment configuration, database models,
read-only administration, and a read-only ESPN sync command.

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
Use `/admin/` to inspect models and `/health/` for a database readiness check.
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
Concurrent scheduling and snapshot retention are deferred to phase 4; run one
sync at a time until that scheduler is implemented.

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
No periodic sync or roster tasks are installed yet. Run one beat instance when
scheduling is introduced. Configure the host build to install from `uv.lock`;
this repository has not yet been deployed.

```bash
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
uv run python manage.py check --deploy
```

WhiteNoise serves collected static files. Verify host/proxy configuration,
database backups, and deployment secrets against the
[Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
The old development secret has been removed from settings; never reuse it.

## Next phases

Phase 4 adds scheduled synchronization and shadow lineup recommendations. ESPN
write validation, policy enforcement, notifications, MCP access, and deployment
rollout remain later milestones. `Decision`, `RosterAction`, `AuditEvent`, and
`ManagerPolicy` are data foundations for that work, not active executors.
