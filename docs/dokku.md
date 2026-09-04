# Deploy fantasy to fantasy.home

Deployment target: `dokku@fantasy.home:fantasy`.
This checkout uses a Dockerfile with Python 3.14 and production dependencies from
`uv.lock`. Dokku 0.31+ is required for the `app.json` startup check.

## Existing app configuration

The `fantasy` Dokku app is already provisioned. No app or service creation is
needed as part of this repository change. Preserve its existing service links,
domains, TLS setup, and secrets.

The app expects `DATABASE_URL` (PostgreSQL), `REDIS_URL`, and a unique production
`SECRET_KEY` in Dokku configuration. ESPN sync additionally needs `ESPN_S2`,
`ESPN_SWID`, `ESPN_LEAGUE_ID`, `ESPN_TEAM_ID`, and `ESPN_SEASON=2026`. The landing
page works before ESPN is configured.

The Dockerfile is detected automatically unless a different builder has been
explicitly selected on the existing app. In that case, select `dockerfile` before
the next deployment. The following settings are a reference for the existing app,
not a provisioning script.

For a site served as `https://fantasy.home`, set:

```sh
dokku domains:set fantasy fantasy.home
dokku config:set --no-restart fantasy \
  DEBUG=false \
  ALLOWED_HOSTS=fantasy.home,localhost,127.0.0.1 \
  CSRF_TRUSTED_ORIGINS=https://fantasy.home \
  TRUST_PROXY_SSL_HEADER=true \
  SECURE_SSL_REDIRECT=true \
  AUTOPILOT_ENABLED=false \
  SHADOW_MODE=true \
  PORT=8000
```

The SSH hostname need not be the web hostname. If a different web domain or
reverse proxy is already configured, preserve it and substitute that hostname in
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and the Dokku domain configuration.
Keep `localhost` allowed for the internal readiness check.

Use the server's existing TLS setup or a trusted internal certificate for
`fantasy.home`. An internal `.home` name needs internal DNS and internal TLS;
do not request a public Let's Encrypt certificate for it. Django keeps secure
cookies and HTTPS redirects enabled. The proxy must replace forwarded protocol
headers. Confirm TLS and proxy configuration before signing in.

## Deploy from this repository

Authorize this Mac's public SSH key with Dokku before deploying. Authentication
can be checked without changing the server:

```sh
ssh dokku@fantasy.home apps:exists fantasy
```

Then use the deployment remote (add it only if absent):

```sh
git remote add dokku dokku@fantasy.home:fantasy
git push dokku HEAD:main
```

Only committed changes are pushed. The predeploy task applies migrations and
collects static files once, before traffic switches. A startup check calls the
container's HTTP health endpoint and verifies the database response.

`app.json` initially runs one web process. Worker and beat stay at zero because
this release does not schedule tasks. Redis is ready for later phases; when
scheduled tasks are implemented, explicitly update formation and run one beat.

After deployment, inspect ports; the Dockerfile exposes port 8000. Preserve any
existing proxy/TLS mappings and ensure the public HTTP/HTTPS ports route to
container port 8000. Verify the service and create an admin account:

```sh
ssh dokku@fantasy.home ports:report fantasy
ssh dokku@fantasy.home checks:run fantasy
ssh dokku@fantasy.home urls fantasy
ssh -t dokku@fantasy.home run fantasy python manage.py createsuperuser
ssh dokku@fantasy.home run fantasy python manage.py sync_espn_league --check-auth
ssh dokku@fantasy.home run fantasy python manage.py sync_espn_league
```

The landing page is `/`; the administration URL is `/fantasy-backend/` and has no
link on the landing page. The sync remains strictly read-only toward ESPN.

## Local image validation

With Docker running:

```sh
docker build -t fantasy:local .
```

Never pass ESPN cookies or the production secret as Docker build arguments.
`.dockerignore` excludes local environments, credentials, and SQLite data.
Production state belongs in the linked PostgreSQL service, not the container.

References: [Dockerfile deployments](https://dokku.com/docs/deployment/builders/dockerfiles/),
[predeploy tasks](https://dokku.com/docs/advanced-usage/deployment-tasks/),
[startup checks](https://dokku.com/docs/deployment/zero-downtime-deploys/).
