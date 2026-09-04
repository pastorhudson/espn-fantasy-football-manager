# Roadmap

This file tracks implementation progress and remaining milestones. Setup and
operating instructions live in [README.md](README.md); deployment instructions
live in [docs/dokku.md](docs/dokku.md).

## Phases 1–3 — Foundation and read-only ESPN synchronization

Status: implemented; deployed web service and manual ESPN sync verified.

- [x] Environment configuration and Django application setup.
- [x] League, team, player, snapshot, policy, decision, action, and audit models.
- [x] Read-only domain administration and database health endpoint.
- [x] ESPN authentication check and manual league synchronization.
- [x] Historical roster, matchup, and bounded free-agent observations.
- [x] Atomic persistence, bounded HTTP retries, and sanitized ESPN errors.
- [x] Dokku deployment configuration and live manual-sync verification.

## Phase 4 — Scheduled synchronization and shadow recommendations

Status: complete; deployed scheduled synchronization and shadow decision
persistence verified on September 4, 2026. Local validation: 36 tests passing.

- [x] Opt-in Celery beat schedule with configurable sync interval.
- [x] Shared database lease for manual and scheduled syncs, with expiration
      checks before persistence.
- [x] Shadow lineup evaluation using projections, eligibility, and lineup rules,
      including global flex-slot assignment.
- [x] Saved decisions with proposed changes, projected totals, and warnings.
- [x] Block recommendations when required data is missing, snapshots are stale,
      or starter slots cannot be filled.
- [x] Flag injury concerns and zero projections; exclude unavailable and IR players.
- [x] Snapshot retention that preserves decision evidence and latest observations.
- [x] Failure audit entries and schedule enable/disable command.
- [x] Deploy Phase 4 and apply its migration on Dokku.
- [x] Enable the schedule and start one worker and one beat process.
- [x] Verify a scheduled sync and shadow decision in the deployed application.

Production verification: the operator confirmed the enabled schedule and one each
of web, worker, and beat. The worker completed `sync_and_recommend` at
04:34:45 UTC on September 4, 2026, returning decision 1 with status `unchanged`.
The admin showed that decision linked to roster snapshot 14, with shadow mode
enabled, no proposed changes, a projected total of 115.78, and recorded warnings.

Phase 4 recommendations remain advisory. Its original evaluator did not verify
game locks or bye status. There is no ESPN write transport or executor. Autopilot and policy flags cannot
enable ESPN writes.

## Later milestones — Scope recorded; phase numbering to be defined

### On-demand updates

- [x] Add an authenticated, permission-controlled **Update now** button that queues
      Celery work and displays progress on the decisions page.
- [x] Share a database enqueue gate with scheduled updates; reject repeated
      requests, duplicate delivery, and expired tokens. Include imminent-schedule
      checks, a completion/failure cooldown, and abandoned-job recovery.
- [ ] Deploy the update reservation migration and verify a button-triggered update
      alongside the existing beat schedule in production.

### Better decision inputs and evidence

Budget: free sources only; no paid subscriptions. FantasyPros free-tier access
is for sample/non-production data and is not used by this application. Paid
FantasyPros and SportsDataIO integrations are deferred unless that constraint changes.

Status: the initial free-source implementation is complete locally; production
rollout remains pending. ESPN remains the sole numerical projection source.

- [x] Add free ESPN NFL schedule observations, explicit bye exclusions, and
      kickoff checks. Block on missing/conflicting schedules or started games;
      do not infer a bye from missing data or claim that ESPN locks are verified.
- [x] Preserve each roster slot's observed NFL team for historical schedule checks.
- [x] Match [Sleeper](https://docs.sleeper.com/) players by explicit ESPN IDs,
      rejecting ambiguous matches; show injury/practice context with retrieval
      timestamps and unknown source-update times clearly labeled.
- [x] Add Sleeper trending adds for waiver discovery, intersected with the saved
      ESPN free-agent/waiver sample. Preserve the observed status and sample time.
- [x] Save bounded source evidence and evaluator version with each decision;
      display schedule context, waiver watch, source status, and warnings.
- [x] Cache free feeds, bound retries, and record source outages without using
      expired cached data. Optional Sleeper failures preserve ESPN evaluation;
      schedule failures block it.
- [ ] Deploy the migrations and verify a fresh scheduled decision with free-source
      evidence. Older snapshots without observed NFL teams need a new ESPN sync.
- [ ] Add reliable confirmed-inactive checks and validate ESPN roster-lock behavior
      before proposing changes around games that have started.
- [ ] Identify a documented free production source for independent projections
      and player-linked news. Confirm coverage, terms, and freshness first.
- [ ] Normalize independent projected statistics to the league's scoring rules;
      keep expert rankings distinct from numerical projections.
- [ ] Compare independent projections against ESPN before adopting any blend.
- [ ] Show player-linked news with publication times and source links; initially
      prompt review rather than automatically subtracting projected points.
- [ ] Extend Sleeper context with trending drops where useful.
- [ ] Explore [nflverse](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)
      performance history, snap counts, and depth charts for workload trends
      and retrospective evaluation. Verify current dataset availability; do not
      rely on its unavailable injury feed for live availability checks.
- [ ] Add [National Weather Service](https://www.weather.gov/documentation/services-web-API)
      forecasts and alerts for outdoor stadiums, accounting for game time and
      roof status; surface warnings before introducing scoring adjustments.
- [ ] Compare predictions with actual results to assess whether additional
      sources improve recommendations over the ESPN-only baseline.

### Controlled execution and delivery

- [ ] ESPN write validation, including game-lock checks before roster changes.
- [ ] Policy enforcement and controlled roster-action execution.
- [ ] Notifications for decisions, failures, and required manager action.
- [ ] MCP access to the manager's capabilities.
- [ ] Deployment rollout and verification of these capabilities.

`ManagerPolicy` and `RosterAction` currently provide data foundations for these
milestones; they do not enforce policies or execute roster changes.
