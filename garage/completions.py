"""Atomic, retry-safe quick completion using ordinary service records."""
from django.core.exceptions import ValidationError
from django.db import transaction

from .forms import validate_timeline
from .models import CompletionSubmission, ServiceRecord, Vehicle
from .services import applicable_rules


@transaction.atomic
def complete_services(vehicle, data):
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle.pk, garage_id=vehicle.garage_id)
    item_ids = sorted({item.pk for item in data["items"]})
    if not item_ids or not set(item_ids).issubset({rule.item_id for rule in applicable_rules(vehicle)}):
        raise ValidationError("The selected services have changed. Reload the vehicle and select them again.")
    payload = {"items": item_ids, "date": data["date"].isoformat(), "miles": data["miles"],
               "engine_hours": data.get("engine_hours")}
    receipt = CompletionSubmission.objects.filter(token=data["token"]).first()
    if receipt:
        if receipt.vehicle_id != vehicle.pk or receipt.payload != payload:
            raise ValidationError("This submission was already used with different details. Start a new completion from the vehicle page.")
        return receipt, False
    validate_timeline(vehicle, data["date"], data["miles"])
    receipt = CompletionSubmission.objects.create(token=data["token"], vehicle=vehicle, payload=payload)
    for item_id in item_ids:
        ServiceRecord.objects.create(vehicle=vehicle, item_id=item_id, completion=receipt,
                                     date=data["date"], miles=data["miles"], engine_hours=data.get("engine_hours"))
    return receipt, True
