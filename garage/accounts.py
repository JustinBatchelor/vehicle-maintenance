"""Google-only authentication and explicit, atomic legacy-garage claims."""
import hashlib
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.google.views import oauth2_login, oauth2_callback
from .models import Garage
from .limits import consume, client_key


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False  # No local signup; social signup has its own adapter.

    def respond_user_inactive(self, request, user):
        messages.error(request, "This account is inactive. Contact the administrator.")
        return redirect("account_login")

    def get_login_redirect_url(self, request):
        return reverse('account-welcome')


class GoogleAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return sociallogin.account.provider == 'google'

    def pre_social_login(self, request, sociallogin):
        verified = any(e.verified and e.email for e in sociallogin.email_addresses)
        if sociallogin.account.provider != 'google' or not verified:
            messages.error(request, 'Google must provide a verified email address to sign in.')
            raise ImmediateHttpResponse(redirect('account_login'))
        if sociallogin.state.get('process') == 'connect':
            raise ImmediateHttpResponse(redirect('account_login'))
        if not sociallogin.is_existing and get_user_model().objects.filter(email__iexact=sociallogin.user.email).exists():
            messages.error(request, 'An account already uses this email. Sign in with its original Google account; accounts are not merged by email.')
            raise ImmediateHttpResponse(redirect('account_login'))

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        messages.error(request, 'Google sign-in was cancelled or could not be completed. Please try again.')
        raise ImmediateHttpResponse(redirect('account_login'))


def authenticated(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.google_authenticated:
            return redirect('account_login')
        return view(request, *args, **kwargs)
    return wrapped


@never_cache
def login_page(request):
    if request.google_authenticated:
        return redirect('account-welcome')
    return render(request, 'account/login.html')


@require_POST
@never_cache
def google_login(request):
    if request.google_authenticated:
        return redirect('account-welcome')
    if not consume('google-login:'+client_key(request), 20, 900):
        return HttpResponse('Too many sign-in attempts. Please try again in 15 minutes.', status=429)
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return render(request, 'account/unavailable.html', status=503)
    # A legacy ID is trusted only from this server-side session, never a URL/form ID.
    gid = request.session.get('garage_id')
    if gid and Garage.objects.filter(pk=gid, owner__isnull=True).exists():
        request.session['pending_garage_id'] = gid
    # Never accept user-controlled next/process/scope parameters for the handshake.
    request.GET = request.GET.copy(); request.GET.clear()
    request.POST = request.POST.copy(); request.POST.clear()
    return oauth2_login(request)


@never_cache
def google_callback(request):
    if not consume('google-callback:'+client_key(request), 60, 900):
        return HttpResponse('Too many sign-in attempts. Please try again later.', status=429)
    return oauth2_callback(request)


def pending_garage(request):
    gid = request.session.get('pending_garage_id')
    return Garage.objects.filter(pk=gid, owner__isnull=True).first() if gid else None


@authenticated
def welcome(request):
    pending = pending_garage(request)
    if pending:
        return redirect('garage-claim')
    if not request.garage:
        # Serialize simultaneous first logins for the same account.
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            Garage.objects.get_or_create(owner=request.user)
    return redirect('home')


@authenticated
def claim(request):
    source = pending_garage(request)
    if not source:
        messages.info(request, 'There is no unclaimed garage available in this browser.')
        request.session.pop('pending_garage_id', None)
        return redirect('account-welcome')
    if request.method == 'POST':
        if not consume('claim:'+str(request.user.pk), 10, 900):
            return HttpResponse('Too many import attempts. Please try later.', status=429)
        if request.POST.get('action') == 'skip':
            request.session['deferred_garage_id'] = request.session.pop('pending_garage_id', None)
            return redirect('account-welcome')
        if request.POST.get('action') != 'claim':
            return HttpResponse('Choose whether to attach this garage.', status=400)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            source = Garage.objects.select_for_update().filter(pk=source.pk, owner__isnull=True).first()
            if not source:
                messages.error(request, 'This garage has already been attached to an account.')
            else:
                destination = Garage.objects.filter(owner=request.user).first()
                if destination and destination.vehicles.count()+source.vehicles.count() > 30:
                    messages.error(request, 'Import would exceed the 30-vehicle limit. No vehicles were moved.')
                    return render(request, 'account/claim.html', {'source':source, 'destination':destination}, status=409)
                if destination:
                    source.vehicles.update(garage=destination)
                    source.delete()
                else:
                    source.owner = request.user
                    source.recovery_hash = None
                    source.save(update_fields=['owner','recovery_hash'])
                messages.success(request, 'Your garage is connected to Google and available on your other devices.')
        request.session.pop('pending_garage_id', None)
        request.session.pop('garage_id', None)
        return redirect('account-welcome')
    return render(request, 'account/claim.html', {'source':source, 'destination':request.garage})


@authenticated
def import_legacy(request):
    if request.method == 'POST':
        if not consume('import-ip:'+client_key(request), 10, 900) or not consume('import-user:'+str(request.user.pk), 10, 900):
            return HttpResponse('Too many recovery attempts. Please try again in 15 minutes.', status=429)
        code = request.POST.get('code','').strip()
        source = Garage.objects.filter(owner__isnull=True,recovery_hash=hashlib.sha256(code.encode()).hexdigest()).first() if code else None
        if source:
            request.session['pending_garage_id'] = str(source.pk)
            return redirect('garage-claim')
        messages.error(request, 'That code does not identify an unclaimed garage.')
    return render(request, 'account/import.html')


@require_POST
@never_cache
def sign_out(request):
    logout(request)
    return redirect('home')


@never_cache
def admin_login(request, extra_context=None):
    if request.google_authenticated:
        if request.user.is_staff:
            return redirect('admin:index')
        return HttpResponse('This account does not have administrator access.', status=403)
    return redirect('account_login')


@authenticated
@require_POST
def resume_claim(request):
    gid=request.session.get('deferred_garage_id') or request.session.get('garage_id')
    if gid and Garage.objects.filter(pk=gid,owner__isnull=True).exists():
        request.session['pending_garage_id']=gid
    return redirect('garage-claim')
