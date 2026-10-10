from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.utils import timezone
from .models import Garage

class GarageMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        request.garage = None
        gid = request.session.get("garage_id")
        if gid:
            request.garage = Garage.objects.filter(pk=gid).first()
        if request.garage:
            try: timezone.activate(ZoneInfo(request.garage.timezone))
            except ZoneInfoNotFoundError: timezone.activate("America/New_York")
        try: return self.get_response(request)
        finally: timezone.deactivate()
