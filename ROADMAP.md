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

Recommendations remain advisory. Game locks and bye status are unverified, and
there is no ESPN write transport or executor. Autopilot and policy flags cannot
enable ESPN writes.

## Later milestones — Scope recorded; phase numbering to be defined

- [ ] ESPN write validation, including game-lock checks before roster changes.
- [ ] Policy enforcement and controlled roster-action execution.
- [ ] Notifications for decisions, failures, and required manager action.
- [ ] MCP access to the manager's capabilities.
- [ ] Deployment rollout and verification of these capabilities.

`ManagerPolicy` and `RosterAction` currently provide data foundations for these
milestones; they do not enforce policies or execute roster changes.
