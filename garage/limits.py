import hashlib
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import UsageCounter

def consume(key, limit, seconds):
    now = timezone.now()
    with transaction.atomic():
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(key=key, defaults={"expires_at": now + timedelta(seconds=seconds)})
        if counter.expires_at <= now:
            counter.count, counter.expires_at = 0, now + timedelta(seconds=seconds)
        if counter.count >= limit: return False
        counter.count += 1
        counter.save()
    return True

def client_key(request):
    # The application is behind the OpenShift router; use its appended client address.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip()
    return hashlib.sha256((forwarded or request.META.get("REMOTE_ADDR", "unknown")).encode()).hexdigest()
