"""Save a current odometer observation without changing maintenance history."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .forms import validate_timeline
from .models import OdometerReading, Vehicle


@transaction.atomic
def update_current_mileage(vehicle, miles):
    vehicle = Vehicle.objects.select_for_update().get(pk=vehicle.pk, garage_id=vehicle.garage_id)
    today = timezone.localdate()
    # Same-day retries remain harmless even after a subsequent mileage update.
    existing = vehicle.readings.filter(date=today, miles=miles).first()
    if existing:
        return existing, False
    latest = vehicle.latest_reading
    if latest and miles < latest.miles:
        raise ValidationError(
            "Mileage cannot be lower than the latest reading or service record. "
            "Use Correct reading or Correct record to fix an earlier entry.")
    validate_timeline(vehicle, today, miles)
    reading = OdometerReading.objects.create(vehicle=vehicle, date=today, miles=miles)
    return reading, True
