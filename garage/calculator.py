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

def calculate(rule: Rule, *, today: date, miles: int, in_service: date | None,
              services: list[Service], engine_hours: int | None = None, never_serviced: bool = False) -> Due:
    if rule.basis == "conditional":
        return Due("as-needed", reason="Follow the condition described in the manufacturer note.")
    past = [s for s in services if s.date <= today]
    if not past and not never_serviced:
        return Due("unknown", unknown=True, reason="No completed service recorded. Add previous work to establish a baseline.")
    last = max(past, key=lambda s: (s.date, s.miles)) if past else None
    target_miles = target_date = remaining_hours = None
    missing = False
    if rule.miles:
        target_miles = (rule.first_miles or rule.miles) if last is None else (last.miles + rule.miles if rule.basis == "service" else
                        next_milestone(last.miles, rule.first_miles or rule.miles, rule.miles))
    if rule.months:
        if last is None:
            if in_service: target_date = in_service + relativedelta(months=rule.first_months or rule.months)
            else: missing = True
        elif rule.basis == "service":
            target_date = last.date + relativedelta(months=rule.months)
        elif in_service:
            age = max(0, (last.date.year - in_service.year) * 12 + last.date.month - in_service.month)
            month = next_milestone(age, rule.first_months or rule.months, rule.months)
            target_date = in_service + relativedelta(months=month)
            # A service just before an anniversary doesn't satisfy the next milestone.
            prev = month - rule.months
            if prev >= (rule.first_months or rule.months) and in_service + relativedelta(months=prev) > last.date:
                target_date = in_service + relativedelta(months=prev)
        else:
            missing = True
    if rule.hours:
        if engine_hours is None or (last is not None and last.engine_hours is None):
            missing = True
        else:
            remaining_hours = (last.engine_hours if last else 0) + rule.hours - engine_hours
    rm = target_miles - miles if target_miles is not None else None
    rd = (target_date - today).days if target_date is not None else None
    values = [v for v in (rm, rd, remaining_hours) if v is not None]
    if any(v < 0 for v in values): status = "overdue"
    elif any(v == 0 for v in values): status = "due"
    elif missing: status = "unknown"
    elif (rm is not None and rm <= 500) or (rd is not None and rd <= 30): status = "due-soon"
    else: status = "upcoming"
    return Due(status, target_miles, target_date, rm, rd, remaining_hours, missing,
               "Original in-service date or engine-hour history is missing; known limits still apply." if missing else "")
