from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.conf import settings
from django.utils import timezone
from allauth.socialaccount.models import SocialAccount
from .models import Garage


class GarageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.garage = None
        request.google_authenticated = request.user.is_authenticated and SocialAccount.objects.filter(user=request.user,provider='google').exists()
        request.google_auth_required = settings.GOOGLE_AUTH_REQUIRED
        if request.google_authenticated:
            request.garage = Garage.objects.filter(owner=request.user).first()
        elif not settings.GOOGLE_AUTH_REQUIRED:
            gid = request.session.get('garage_id')
            if gid:
                request.garage = Garage.objects.filter(pk=gid,owner__isnull=True).first()
        if request.garage:
            try: timezone.activate(ZoneInfo(request.garage.timezone))
            except ZoneInfoNotFoundError: timezone.activate('America/New_York')
        try: return self.get_response(request)
        finally: timezone.deactivate()
