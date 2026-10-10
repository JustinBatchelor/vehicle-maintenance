from datetime import timedelta
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from garage.models import VideoSearchCache,UsageCounter
class Command(BaseCommand):
    help="Delete expired sessions/counters and YouTube metadata older than 30 days. Never deletes garages."
    def handle(self,*args,**kwargs):
        VideoSearchCache.objects.filter(fetched_at__lt=timezone.now()-timedelta(days=30)).delete()
        VideoSearchCache.objects.filter(fetched_at__isnull=True,lease_until__lt=timezone.now()).delete()
        UsageCounter.objects.filter(expires_at__lt=timezone.now()).delete()
        call_command("clearsessions")
