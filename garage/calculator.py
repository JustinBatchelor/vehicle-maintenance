"""Pure schedule calculation. No database, clock, network, or inferred driving rate."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from dateutil.relativedelta import relativedelta

@dataclass(frozen=True)
class Rule:
    miles: int | None = None
    months: int | None = None
    first_miles: int | None = None
    first_months: int | None = None
    hours: int | None = None
    basis: str = "milestone"

@dataclass(frozen=True)
class Service:
    date: date
    miles: int
    engine_hours: int | None = None

@dataclass(frozen=True)
class Baseline:
    """User assumption that scheduled work through this point was completed."""
    date: date
    miles: int
    engine_hours: int | None = None

@dataclass(frozen=True)
class Due:
    status: str
    miles: int | None = None
    date: date | None = None
    remaining_miles: int | None = None
    remaining_days: int | None = None
    remaining_hours: int | None = None
    unknown: bool = False
    reason: str = ""
    @property
    def label(self):
        return {"unknown": "Unknown history", "due-soon": "Due soon", "as-needed": "As needed"}.get(self.status, self.status.capitalize())

def next_milestone(value, first, interval):
    if value < first:
        return first
    return first + ((value - first) // interval + 1) * interval

def next_date_milestone(through, in_service, first, interval):
    age = max(0, (through.year - in_service.year) * 12 + through.month - in_service.month)
    month = next_milestone(age, first, interval)
    previous = month - interval
    if previous >= first and in_service + relativedelta(months=previous) > through:
        month = previous
    return in_service + relativedelta(months=month)

def calculate(rule: Rule, *, today: date, miles: int, in_service: date | None,
              services: list[Service], engine_hours: int | None = None, never_serviced: bool = False,
              baseline: Baseline | None = None) -> Due:
    if rule.basis == "conditional":
        return Due("as-needed", reason="Follow the condition described in the manufacturer note.")
    past = [s for s in services if s.date <= today]
    assumed = baseline if not past and not never_serviced and baseline and baseline.date <= today else None
    if not past and not never_serviced and not assumed:
        return Due("unknown", unknown=True, reason="No completed service recorded. Add previous work to establish a baseline.")
    last = max(past, key=lambda s: (s.date, s.miles)) if past else None
    target_miles = target_date = remaining_hours = None
    missing = False
    if rule.miles:
        if assumed:
            target_miles = next_milestone(assumed.miles, rule.first_miles or rule.miles, rule.miles)
        elif last is None:
            target_miles = rule.first_miles or rule.miles
        elif rule.basis == "service":
            target_miles = last.miles + rule.miles
        else:
            target_miles = next_milestone(last.miles, rule.first_miles or rule.miles, rule.miles)
    if rule.months:
        if assumed:
            if in_service:
                target_date = next_date_milestone(assumed.date, in_service, rule.first_months or rule.months, rule.months)
            else:
                # Vehicle age is unknown: explicitly anchor the assumed time cycle to setup.
                target_date = assumed.date + relativedelta(months=rule.months)
        elif last is None:
            if in_service: target_date = in_service + relativedelta(months=rule.first_months or rule.months)
            else: missing = True
        elif rule.basis == "service":
            target_date = last.date + relativedelta(months=rule.months)
        elif in_service:
            target_date = next_date_milestone(last.date, in_service, rule.first_months or rule.months, rule.months)
        else:
            missing = True
    if rule.hours:
        if engine_hours is None or (last is not None and last.engine_hours is None) or (assumed and assumed.engine_hours is None):
            missing = True
        else:
            target_hours = next_milestone(assumed.engine_hours, rule.hours, rule.hours) if assumed else (last.engine_hours if last else 0) + rule.hours
            remaining_hours = target_hours - engine_hours
    rm = target_miles - miles if target_miles is not None else None
    rd = (target_date - today).days if target_date is not None else None
    values = [v for v in (rm, rd, remaining_hours) if v is not None]
    if any(v < 0 for v in values): status = "overdue"
    elif any(v == 0 for v in values): status = "due"
    elif missing: status = "unknown"
    elif (rm is not None and rm <= 500) or (rd is not None and rd <= 30): status = "due-soon"
    else: status = "upcoming"
    reasons = []
    if assumed:
        reasons.append(f"Prior scheduled maintenance assumed complete through {assumed.miles:,} miles on {assumed.date}; no completed service recorded.")
        if rule.months and not in_service:
            reasons.append("In-service date unknown: time intervals start from the assumption date.")
    if missing:
        reasons.append("Original in-service date or engine-hour history is missing; known limits still apply.")
    return Due(status, target_miles, target_date, rm, rd, remaining_hours, missing, " ".join(reasons))
