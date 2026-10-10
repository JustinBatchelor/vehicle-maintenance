import pytest
from django.core.management import call_command
from django.test import Client
from django.contrib.auth import get_user_model
from allauth.socialaccount.models import SocialAccount
from garage.models import Garage,Vehicle,VehicleConfiguration,OdometerReading
from datetime import date

@pytest.fixture
def catalog(db):
    call_command('import_schedules',verbosity=0)

def account_client(label):
    user=get_user_model().objects.create_user(username=label,email=label+'@example.com')
    SocialAccount.objects.create(user=user,provider='google',uid=label)
    client=Client();client.force_login(user,backend='allauth.account.auth_backends.AuthenticationBackend')
    return client,user

@pytest.fixture
def garage(catalog):
    client,user=account_client('owner')
    return Garage.objects.create(owner=user)

@pytest.fixture
def car(garage):
    c=Vehicle.objects.create(garage=garage,configuration=VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited'),in_service_date=date(2021,1,1))
    OdometerReading.objects.create(vehicle=c,date=date(2026,10,1),miles=50000)
    return c

@pytest.fixture
def browser(garage):
    client=Client();client.force_login(garage.owner,backend='allauth.account.auth_backends.AuthenticationBackend');return client
