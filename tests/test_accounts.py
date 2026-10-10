import hashlib
from urllib.parse import parse_qs,urlparse
from unittest.mock import patch
import pytest
import requests
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from allauth.socialaccount.models import SocialAccount,SocialToken
from garage.models import Garage,Vehicle,VehicleConfiguration,ServiceRecord,MaintenanceItem
from conftest import account_client

@pytest.fixture
def oauth(settings):
    settings.GOOGLE_CLIENT_ID='test-client-id'
    settings.GOOGLE_CLIENT_SECRET='test-secret'
    settings.SOCIALACCOUNT_PROVIDERS={'google':{'APP':{'client_id':'test-client-id','secret':'test-secret','key':''},'SCOPE':['openid','email','profile'],'OAUTH_PKCE_ENABLED':True}}


def google_signin(client,uid='google-1',email='driver@example.com',verified=True):
    response=client.post('/accounts/google/login/')
    assert response.status_code==302
    query=parse_qs(urlparse(response['Location']).query)
    assert set(query['scope'][0].split())=={'openid','email','profile'}
    assert query['redirect_uri']==['http://testserver/accounts/google/login/callback/']
    assert 'code_challenge' in query
    def send(session,method,url,**kwargs):
        response=requests.Response();response.status_code=200;response.headers["content-type"]="application/json"
        if 'token' in url:
            data={'access_token':'test-access-token','token_type':'Bearer','expires_in':3600}
        else:
            data={'id':uid,'email':email,'verified_email':verified,'given_name':'Driver'}
        import json
        response._content=json.dumps(data).encode();return response
    with patch('requests.sessions.Session.request',send):
        result=client.get('/accounts/google/login/callback/',{'code':'test-code','state':query['state'][0]})
    return result


def test_google_signup_repeat_login_and_no_tokens(catalog,oauth):
    first=Client();assert google_signin(first).status_code==302
    assert first.session.get('_auth_user_id')
    first.get('/accounts/welcome/')
    owner=Garage.objects.get().owner
    assert owner.email=='driver@example.com' and not owner.has_usable_password()
    assert not SocialToken.objects.exists()
    assert 'test-access-token' not in str(dict(first.session))
    second=Client();google_signin(second);second.get('/accounts/welcome/')
    assert second.session['_auth_user_id']==first.session['_auth_user_id']
    assert Garage.objects.count()==1 and get_user_model().objects.count()==1
    assert second.get('/').status_code==200
    assert first.post('/accounts/logout/').status_code==302
    assert not first.session.get('_auth_user_id') and second.get('/settings/').status_code==200


def test_google_rejects_unverified_and_email_merge(catalog,oauth):
    client=Client();google_signin(client,verified=False)
    assert not client.session.get('_auth_user_id') and not get_user_model().objects.exists()
    existing=get_user_model().objects.create_user(username='local',email='driver@example.com')
    google_signin(client)
    assert not client.session.get('_auth_user_id') and not SocialAccount.objects.exists()
    assert get_user_model().objects.count()==1


def test_cancel_invalid_state_and_replay(catalog,oauth):
    client=Client()
    for params in [{'error':'access_denied'},{'code':'fake','state':'wrong'}]:
        response=client.get('/accounts/google/login/callback/',params)
        assert response.status_code in (200,302,400)
        assert not client.session.get('_auth_user_id')
    assert not Garage.objects.exists()


def test_public_entrypoints_and_csrf(catalog,oauth):
    client=Client(enforce_csrf_checks=True)
    assert client.get('/accounts/login/').status_code==200
    assert client.get('/accounts/google/login/').status_code==405
    assert client.post('/accounts/google/login/').status_code==403
    assert client.post('/accounts/logout/').status_code==403
    for path in ['/accounts/signup/','/accounts/password/reset/','/accounts/password/change/','/accounts/google/login/token/','/accounts/social/connections/']:
        assert client.get(path).status_code==404
    assert client.get('/admin/login/').status_code==302
    plain=Client();assert plain.post('/start/').status_code==302
    assert not Garage.objects.exists()


def test_claim_preserves_garage_and_invalidates_legacy_access(catalog,oauth,settings):
    legacy=Garage.objects.create(name='Original',timezone='UTC',recovery_hash=hashlib.sha256(b'legacy').hexdigest())
    vehicle=Vehicle.objects.create(garage=legacy,configuration=VehicleConfiguration.objects.first(),nickname='Keep me')
    first=Client();session=first.session;session['garage_id']=str(legacy.pk);session.save()
    google_signin(first);assert first.get('/accounts/welcome/')['Location']=='/accounts/claim/'
    assert first.post('/accounts/claim/',{'action':'claim'}).status_code==302
    legacy.refresh_from_db();vehicle.refresh_from_db()
    assert legacy.owner_id and legacy.name=='Original' and legacy.timezone=='UTC' and legacy.recovery_hash is None
    assert vehicle.garage_id==legacy.pk
    assert first.post('/accounts/claim/',{'action':'claim'}).status_code==302
    settings.GOOGLE_AUTH_REQUIRED=False
    old=Client();session=old.session;session['garage_id']=str(legacy.pk);session.save()
    assert old.get(reverse('vehicle-detail',args=[vehicle.pk])).status_code==302
    assert old.post('/recover/',{'code':'legacy'}).status_code==200
    assert old.session.get('garage_id')==str(legacy.pk)  # inert: middleware rejects owned garages


def test_import_requires_google_and_confirmation(browser,garage):
    source=Garage.objects.create(name='Old',recovery_hash=hashlib.sha256(b'code').hexdigest())
    car=Vehicle.objects.create(garage=source,configuration=VehicleConfiguration.objects.first())
    assert Client().post('/accounts/import/',{'code':'code'}).status_code==302
    browser.post('/accounts/import/',{'code':'code'})
    car.refresh_from_db();assert car.garage_id==source.pk
    assert browser.get('/accounts/claim/').status_code==200
    browser.post('/accounts/claim/',{'action':'claim'})
    car.refresh_from_db();assert car.garage_id==garage.pk and not Garage.objects.filter(pk=source.pk).exists()
    assert browser.post('/accounts/import/',{'code':'code'}).status_code==200


def test_import_limit_is_atomic(browser,garage):
    source=Garage.objects.create(recovery_hash=hashlib.sha256(b'code').hexdigest())
    config=VehicleConfiguration.objects.first()
    Vehicle.objects.bulk_create([Vehicle(garage=garage,configuration=config) for _ in range(30)])
    car=Vehicle.objects.create(garage=source,configuration=config)
    browser.post('/accounts/import/',{'code':'code'})
    assert browser.post('/accounts/claim/',{'action':'claim'}).status_code==409
    car.refresh_from_db();source.refresh_from_db()
    assert car.garage_id==source.pk and source.owner_id is None and source.recovery_hash


def test_two_accounts_cannot_claim_same_garage(catalog):
    source=Garage.objects.create()
    first,a=account_client('first');second,b=account_client('second')
    for client in [first,second]:
        session=client.session;session['pending_garage_id']=str(source.pk);session.save()
    first.post('/accounts/claim/',{'action':'claim'})
    second.post('/accounts/claim/',{'action':'claim'})
    source.refresh_from_db();assert source.owner_id==a.pk
    assert not Garage.objects.filter(owner=b).exists()


def test_no_claim_by_submitted_id(browser,garage):
    source=Garage.objects.create()
    browser.post('/accounts/claim/',{'action':'claim','garage_id':str(source.pk)})
    source.refresh_from_db();assert source.owner_id is None


def test_login_limits_and_missing_configuration(catalog,oauth,settings):
    client=Client()
    for _ in range(20):assert client.post('/accounts/google/login/').status_code==302
    assert client.post('/accounts/google/login/').status_code==429
    settings.GOOGLE_CLIENT_SECRET=''
    assert Client(REMOTE_ADDR='192.0.2.2').post('/accounts/google/login/').status_code==503


def test_admin_requires_google_and_staff(catalog):
    client,user=account_client('normal')
    assert client.get('/admin/login/').status_code==403
    user.is_staff=True;user.save()
    assert client.get('/admin/').status_code==200
    user2=get_user_model().objects.create_user(username='password-admin',is_staff=True)
    local=Client();local.force_login(user2,backend='allauth.account.auth_backends.AuthenticationBackend')
    assert local.get('/admin/').status_code==302


def test_deferred_claim_can_be_resumed(browser,garage):
    source=Garage.objects.create()
    session=browser.session;session['pending_garage_id']=str(source.pk);session.save()
    browser.post('/accounts/claim/',{'action':'skip'})
    assert browser.get('/accounts/welcome/')['Location']=='/'
    browser.post('/accounts/claim/resume/')
    assert browser.get('/accounts/claim/').status_code==200
    browser.post('/accounts/claim/',{'action':'claim'})
    assert not Garage.objects.filter(pk=source.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_are_exclusive(catalog):
    from django.db import connection,close_old_connections
    if connection.vendor!='postgresql':pytest.skip('Row-lock concurrency verified on PostgreSQL')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from garage import accounts
    source=Garage.objects.create()
    first,a=account_client('racer-a');second,b=account_client('racer-b')
    for client in (first,second):
        session=client.session;session['pending_garage_id']=str(source.pk);session.save()
    barrier=Barrier(2);original=accounts.pending_garage
    def pending(request):
        value=original(request);barrier.wait(timeout=15);return value
    def claim(client):
        close_old_connections()
        try:return client.post('/accounts/claim/',{'action':'claim'}).status_code
        finally:connection.close()
    with patch('garage.accounts.pending_garage',pending),ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(claim,[first,second]))==[302,302]
    source.refresh_from_db();assert source.owner_id in (a.pk,b.pk)
    assert Garage.objects.filter(owner__isnull=False).count()==1


def test_disabled_google_account_cannot_sign_in(catalog,oauth):
    client=Client();google_signin(client)
    user=get_user_model().objects.get();user.is_active=False;user.save()
    client=Client();response=google_signin(client)
    assert response.status_code==302 and not client.session.get('_auth_user_id')
