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

`app.json` runs one web, one worker, and one beat process. Redis is required.
Scheduling is opt-in (see the Phase 4 section in README.md). The `formation`
configuration controls process counts and prevents manual scaling with
`dokku ps:scale fantasy web=1 worker=1 beat=1`. Change quantities in `app.json`
and redeploy when needed; keep exactly one beat process. Use
`dokku ps:scale fantasy` without counts to inspect the deployed formation.

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

## Replace legacy Docker links with a custom network

For the existing `fantasy-db` and `fantasy-redis` services, create a shared
network and persist their attachment settings. These server commands are a
migration procedure, not confirmation that it has been applied. Stop if any
command fails. If `fantasy-net` already exists, skip its creation.

```sh
dokku network:create fantasy-net
dokku postgres:set fantasy-db post-create-network fantasy-net
dokku redis:set fantasy-redis post-create-network fantasy-net
```

Attach the running service containers with the DNS aliases already used by their
connection URLs. This avoids restarting PostgreSQL and Redis. The settings above
preserve those attachments when the service containers are recreated.

```sh
sudo docker network connect --alias dokku-postgres-fantasy-db fantasy-net "$(dokku postgres:info fantasy-db --id)"
sudo docker network connect --alias dokku-redis-fantasy-redis fantasy-net "$(dokku redis:info fantasy-redis --id)"
dokku network:set fantasy attach-post-create fantasy-net
```

Remove only the legacy Docker options; do not use service `unlink`, which would
also remove connection configuration. Rebuild the app to apply the changes to
all process types.

```sh
dokku docker-options:remove fantasy build,deploy,run "--link dokku.postgres.fantasy-db:dokku-postgres-fantasy-db"
dokku docker-options:remove fantasy build,deploy,run "--link dokku.redis.fantasy-redis:dokku-redis-fantasy-redis"
dokku ps:rebuild fantasy
```

Verify database and Redis connectivity from a one-off app container:

```sh
dokku run fantasy python manage.py shell -c 'from django.db import connection; from django.conf import settings; import redis; connection.ensure_connection(); print("PostgreSQL OK"); print("Redis OK:", redis.Redis.from_url(settings.CELERY_BROKER_URL).ping())'
dokku docker-options:report fantasy
dokku network:report fantasy
```

The app should no longer have `--link` options or emit the default-bridge link
warning. Existing proxy ports and connection URLs remain unchanged. Relinking a
service later may recreate legacy options; inspect them if the warning returns.

References: [Dokku networking](https://dokku.com/docs/networking/network/),
[Docker options](https://dokku.com/docs/advanced-usage/docker-options/),
[Postgres plugin](https://github.com/dokku/dokku-postgres),
[Redis plugin](https://github.com/dokku/dokku-redis).
