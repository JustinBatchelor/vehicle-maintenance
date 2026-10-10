import pytest
from django.core.management import call_command
from django.test import Client
from garage.models import Garage,Vehicle,VehicleConfiguration,OdometerReading
from datetime import date

@pytest.fixture
def catalog(db):
    call_command('import_schedules',verbosity=0)

@pytest.fixture
def garage(catalog):return Garage.objects.create()

@pytest.fixture
def car(garage):
    c=Vehicle.objects.create(garage=garage,configuration=VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited'),in_service_date=date(2021,1,1))
    OdometerReading.objects.create(vehicle=c,date=date(2026,10,1),miles=50000)
    return c

@pytest.fixture
def browser(garage):
    client=Client();session=client.session;session['garage_id']=str(garage.pk);session.save();return client
