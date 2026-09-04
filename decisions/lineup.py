"""Projection-only shadow evaluation; never creates executable roster actions."""

import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from decisions.models import Decision
from leagues.models import RosterSnapshot
from roster_actions.models import AuditEvent

BENCH_SLOTS = {20, 21}
UNAVAILABLE = {"OUT", "IR", "INJURY_RESERVE", "SUSPENSION", "SUSPENDED", "DOUBTFUL"}


def evaluate(snapshot, evidence=None):
    rows = list(snapshot.slots.select_related("player").order_by("player__espn_id"))
    warnings = ["Game locks and bye status are unverified; review in ESPN before any change."]
    result = {"status": "blocked", "warnings": warnings, "assignments": [], "changes": []}
    result["evaluator_version"] = "lineup-v2"
    result["lineup_rules"] = snapshot.team.league.settings.get("rosterSettings", {})
    if evidence is not None:
        evidence["evaluated_at"] = timezone.now().isoformat()
        result["evidence"] = evidence
        warnings[:] = ["ESPN roster locks and confirmed inactives remain unverified; review in ESPN."]
        warnings.extend(evidence["warnings"])
    if snapshot.captured_at < timezone.now() - timedelta(hours=2):
        warnings.append("Roster snapshot is older than two hours.")
        return result
    if snapshot.scoring_period != snapshot.team.league.scoring_period:
        warnings.append("Snapshot is not for the league's current scoring period.")
        return result
    try:
        counts = snapshot.team.league.settings["rosterSettings"]["lineupSlotCounts"]
        slots = []
        for key, count in counts.items():
            slot = int(key)
            if not isinstance(count, int) or count < 0:
                raise ValueError
            if slot not in BENCH_SLOTS:
                slots.extend([slot] * count)
        if not slots or len(slots) > 16:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        warnings.append("Missing or unsupported lineup slot counts.")
        return result
    for row in rows:
        if row.injury_status and row.injury_status != "ACTIVE":
            warnings.append(f"{row.player.name}: {row.injury_status}.")
    candidates = [r for r in rows if r.lineup_slot_id != 21 and r.injury_status not in UNAVAILABLE]
    if evidence is not None:
        contexts = {item["player_id"]: item for item in evidence["players"]}
        blocked = False
        # Conservatively stop after any roster player's kickoff. Optimizing around
        # already-locked slots requires separate validation of ESPN lock rules.
        for row in rows:
            if row.lineup_slot_id == 21:
                continue
            context = contexts.get(row.player.espn_id, {})
            state = context.get("state", "unknown")
            if state == "scheduled":
                kickoff = parse_datetime(context["kickoff"])
                if kickoff <= timezone.now():
                    state = "started"
                    context["state"] = state
            if state in ("unknown", "started"):
                reason = "schedule is unknown" if state == "unknown" else "game has started"
                warnings.append(f"{row.player.name}: {reason}; lineup evaluation blocked.")
                blocked = True
            elif state == "bye":
                warnings.append(f"{row.player.name}: confirmed schedule bye; excluded from starters.")
        if blocked:
            return result
        candidates = [r for r in candidates if contexts[r.player.espn_id]["state"] != "bye"]
    if any(
        r.projected_points is None
        or not math.isfinite(r.projected_points)
        or not isinstance(r.eligible_slots, list)
        or not r.eligible_slots
        for r in candidates
    ):
        warnings.append("A roster candidate has missing projection or eligibility data.")
        return result
    for row in candidates:
        if row.projected_points == 0:
            warnings.append(f"{row.player.name}: zero projection requires verification.")
    # Player-by-player assignment DP handles flex slots globally and uses each player once.
    # On equal points, prefer retaining observed slots to avoid gratuitous swaps.
    states = {0: (0.0, 0, [])}
    for row in candidates:
        updated = dict(states)
        for mask, (score, retained, assignment) in states.items():
            for index, slot in enumerate(slots):
                if mask & (1 << index) or slot not in row.eligible_slots:
                    continue
                new_mask = mask | (1 << index)
                candidate = (
                    score + row.projected_points,
                    retained + int(row.lineup_slot_id == slot),
                    assignment + [(index, row)],
                )
                if new_mask not in updated or candidate[:2] > updated[new_mask][:2]:
                    updated[new_mask] = candidate
        states = updated
    best = states.get((1 << len(slots)) - 1)
    if best is None:
        warnings.append("Cannot fill every starter slot with available eligible players.")
        return result
    total, _, assignment = best
    starters = [r for r in rows if r.lineup_slot_id not in BENCH_SLOTS]
    current = None
    if sorted(r.lineup_slot_id for r in starters) == sorted(slots) and all(
        r.projected_points is not None and math.isfinite(r.projected_points) for r in starters
    ):
        current = sum(r.projected_points for r in starters)
    assignments = [
        {
            "player_id": row.player.espn_id,
            "name": row.player.name,
            "slot_id": slots[index],
            "projected_points": row.projected_points,
        }
        for index, row in sorted(assignment)
    ]
    targets = {item["player_id"]: item["slot_id"] for item in assignments}
    changes = [
        {
            "player_id": r.player.espn_id,
            "name": r.player.name,
            "from_slot": r.lineup_slot_id,
            "to_slot": targets.get(r.player.espn_id, 20),
        }
        for r in rows
        if r.lineup_slot_id != 21 and r.lineup_slot_id != targets.get(r.player.espn_id, 20)
    ]
    result.update(
        status="review" if changes else "unchanged",
        assignments=assignments,
        changes=changes,
        projected_total=round(total, 2),
        current_projected_total=None if current is None else round(current, 2),
        improvement=None if current is None else round(total - current, 2),
    )
    return result


def recommend_lineup(snapshot):
    existing = Decision.objects.filter(roster_snapshot=snapshot, kind="shadow_lineup").first()
    if existing:
        return existing
    evidence = None
    if settings.FREE_DATA_ENABLED:
        from decisions.sources.free import collect_context

        evidence = collect_context(snapshot)
    return _save_recommendation(snapshot, evidence)


@transaction.atomic
def _save_recommendation(snapshot, evidence):
    # Serialize repeated evaluations of the same observation.
    snapshot = (
        RosterSnapshot.objects.select_for_update()
        .select_related("team__league")
        .get(pk=snapshot.pk)
    )
    existing = Decision.objects.filter(roster_snapshot=snapshot, kind="shadow_lineup").first()
    if existing:
        return existing
    result = evaluate(snapshot, evidence)
    decision = Decision.objects.create(
        team=snapshot.team,
        roster_snapshot=snapshot,
        kind="shadow_lineup",
        shadow_mode=True,
        rationale="Projection-only lineup evaluation. " + " ".join(result["warnings"]),
        recommendation=result,
    )
    AuditEvent.objects.create(
        league=snapshot.team.league,
        kind="lineup.shadow",
        details={"decision_id": decision.pk, "status": result["status"]},
    )
    return decision
