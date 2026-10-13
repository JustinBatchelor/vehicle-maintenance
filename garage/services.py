from dataclasses import fields
from django.utils import timezone
from .calculator import Rule, Service, Baseline, calculate
from .models import MaintenanceRule

def applicable_rules(vehicle):
    config = vehicle.configuration
    rules = MaintenanceRule.objects.filter(schedule=config.schedule).select_related("item", "schedule__source").order_by("priority", "key")
    selected = {}
    conditions, equipment = set(vehicle.conditions), set(vehicle.equipment)
    for rule in rules:
        if rule.conditions_any and not conditions.intersection(rule.conditions_any): continue
        if conditions.intersection(rule.conditions_none): continue
        if not set(rule.equipment_all).issubset(equipment): continue
        if rule.drivetrain and rule.drivetrain != config.drivetrain: continue
        if rule.transmission and rule.transmission != config.transmission: continue
        selected[rule.item_id] = rule
    return sorted(selected.values(), key=lambda r: r.item.name)

def recommendations(vehicle):
    reading = vehicle.latest_reading
    records = list(vehicle.records.all())
    rows = []
    originals = set(vehicle.original_items.values_list("id", flat=True))
    unknowns = set(vehicle.unknown_items.values_list("id", flat=True))
    baseline = Baseline(vehicle.assumed_through_date, vehicle.assumed_through_miles, vehicle.assumed_through_hours) if vehicle.assumed_through_date is not None and vehicle.assumed_through_miles is not None else None
    for rule in applicable_rules(vehicle):
        history = [Service(r.date, r.miles, r.engine_hours) for r in records if r.item_id == rule.item_id]
        due = calculate(Rule(**{f.name: getattr(rule, f.name) for f in fields(Rule)}), today=timezone.localdate(),
                        miles=reading.miles if reading else 0, in_service=vehicle.in_service_date,
                        engine_hours=reading.engine_hours if reading else None, services=history, never_serviced=rule.item_id in originals,
                        baseline=baseline if rule.item_id not in unknowns else None)
        rows.append({"rule": rule, "item": rule.item, "due": due, "last": max(history, key=lambda s: (s.date,s.miles)) if history else None})
    order = {"overdue": 0, "due": 1, "due-soon": 2, "unknown": 3, "upcoming": 4, "as-needed": 5}
    return sorted(rows, key=lambda r: (order[r["due"].status], r["item"].name))


def maintenance_timeline(rows, reading):
    """Group existing decisions without projecting dates or altering due logic."""
    milestones = {}
    sections = {"scheduled": [], "unknown": [], "conditional": []}
    attention = []
    for row in rows:
        due = row["due"]
        if due.status in {"overdue", "due", "due-soon"} or (due.remaining_days is not None and due.remaining_days <= 30):
            attention.append(row)
        if due.miles is not None:
            milestones.setdefault(due.miles, []).append(row)
        elif due.status == "as-needed":
            sections["conditional"].append(row)
        elif due.date is not None or due.remaining_hours is not None:
            sections["scheduled"].append(row)
        else:
            sections["unknown"].append(row)
    if reading is not None:
        milestones.setdefault(reading.miles, [])
    order = lambda row: (row["rule"].optional, row["item"].name)
    return {
        "milestones": [
            {"miles": miles, "current": reading is not None and miles == reading.miles,
             "rows": sorted(group, key=order)}
            for miles, group in sorted(milestones.items())
        ],
        "sections": [
            {"title": title, "rows": sorted(sections[key], key=order)}
            for key, title in [("scheduled", "Date / engine-hour maintenance"),
                               ("unknown", "Unknown history"), ("conditional", "As needed")]
            if sections[key]
        ],
        "attention": attention,
    }
