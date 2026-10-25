"""Garage-card mileage uses the same owned, transactional save as vehicle pages."""
import re
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from conftest import account_client
from garage.models import Vehicle, OdometerReading, ServiceRecord, MaintenanceItem, Appointment
from garage.services import recommendations


@pytest.fixture(autouse=True)
def today():
    with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 25, 16, tzinfo=dt_timezone.utc)):
        yield


@pytest.fixture
def other_car(car):
    other = Vehicle.objects.create(garage=car.garage, configuration=car.configuration, nickname='Second car')
    OdometerReading.objects.create(vehicle=other, date=date(2026, 10, 1), miles=100)
    return other


def save(browser, car, miles, **kwargs):
    return browser.post(reverse('reading-add', args=[car.pk]),
                        {'mode': 'quick', 'return_to': 'garage', 'miles': miles}, **kwargs)


def test_dashboard_forms_have_unique_ids_and_latest_service_mileage(browser, car, other_car):
    record = ServiceRecord.objects.create(vehicle=car, item=MaintenanceItem.objects.get(key='oil'),
                                          date=date(2026, 10, 25), miles=51000)
    response = browser.get(reverse('home'))
    cards = {c['vehicle'].pk: c for c in response.context['cars']}
    assert cards[car.pk]['mileage_form'].initial['miles'] == 51000
    assert cards[other_car.pk]['mileage_form'].initial['miles'] == 100
    html = response.content.decode()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    for pk in [car.pk, other_car.pk]:
        assert f'for="id_quick_miles_{pk}"' in html
        assert f'aria-describedby="quick-mileage-help-{pk}"' in html
    assert reverse('record-edit', args=[car.pk, record.pk]) in html
    assert reverse('reading-edit', args=[other_car.pk, other_car.latest_reading.pk]) in html
    car.readings.all().delete()
    car.records.all().delete()
    response = browser.get(reverse('home'))
    assert response.context['cars'][0]['mileage_form'].initial['miles'] is None
    assert b'No mileage recorded yet.' in response.content


@pytest.mark.parametrize('miles,status', [(53000, 'upcoming'), (53500, 'due-soon'), (54000, 'due'), (54001, 'overdue')])
def test_save_refreshes_dashboard_and_preserves_history(browser, car, other_car, miles, status):
    car.in_service_date = car.assumed_through_date = date(2026, 10, 1)
    car.assumed_through_miles = 50000
    car.nickname = 'My Crosstrek'
    car.save()
    ServiceRecord.objects.create(vehicle=car, item=MaintenanceItem.objects.get(key='oil'), date=date(2026, 10, 1), miles=48000)
    appointment = Appointment.objects.create(vehicle=car, title='Oil service', date=date(2026, 11, 1))
    before = {r['item'].key: (r['due'].miles, r['due'].date) for r in recommendations(car)}
    response = save(browser, car, miles, follow=True)
    assert response.redirect_chain == [(reverse('home') + f'#vehicle-{car.pk}', 302)]
    rows = recommendations(car)
    assert next(r['due'].status for r in rows if r['item'].key == 'oil') == status
    assert {r['item'].key: (r['due'].miles, r['due'].date) for r in rows} == before
    cards = {c['vehicle'].pk: c for c in response.context['cars']}
    assert cards[car.pk]['reading'].miles == miles
    assert cards[car.pk]['reading'].date == date(2026, 10, 25)
    assert cards[car.pk]['attention'] == sum(not r['rule'].optional and r['due'].status in ('due-soon', 'due', 'overdue') for r in rows)
    all_rows = rows + recommendations(other_car)
    assert response.context['counts'] == {status: sum(not r['rule'].optional and r['due'].status == status for r in all_rows) for status in ('overdue', 'due', 'due-soon', 'unknown')}
    assert any('My Crosstrek: mileage updated.' in str(m) for m in response.context['messages'])
    assert other_car.latest_reading.miles == 100 and other_car.readings.count() == 1
    car.refresh_from_db()
    assert car.assumed_through_miles == 50000 and car.assumed_through_date == date(2026, 10, 1)
    assert car.records.count() == 1 and Appointment.objects.filter(pk=appointment.pk).exists()
    assert car.latest_reading.engine_hours is None


@pytest.mark.parametrize('miles', ['', 'bad', '1.5', -1, 3000001, 49999])
def test_errors_stay_on_affected_card(browser, car, other_car, miles):
    response = save(browser, other_car, 200)
    assert response.status_code == 302
    response = save(browser, car, miles)
    assert response.status_code == 200
    cards = {c['vehicle'].pk: c for c in response.context['cars']}
    form = cards[car.pk]['mileage_form']
    assert form.errors and form.data['miles'] == str(miles)
    assert form['miles'].id_for_label == f'id_quick_miles_{car.pk}'
    assert not cards[other_car.pk]['mileage_form'].is_bound
    assert cards[other_car.pk]['mileage_form'].initial['miles'] == 200
    assert reverse('reading-edit', args=[car.pk, car.latest_reading.pk]) in response.content.decode()
    assert car.readings.count() == 1


def test_same_day_service_decrease_and_duplicate(browser, car):
    record = ServiceRecord.objects.create(vehicle=car, item=MaintenanceItem.objects.get(key='oil'), date=date(2026, 10, 25), miles=51000)
    response = save(browser, car, 50500)
    assert 'latest reading or service' in str(response.context['cars'][0]['mileage_form'].errors)
    assert reverse('record-edit', args=[car.pk, record.pk]) in response.content.decode()
    assert save(browser, car, 52000).status_code == 302
    response = save(browser, car, 52000, follow=True)
    assert car.readings.count() == 2
    assert any('already recorded for today' in str(m) for m in response.context['messages'])
    assert save(browser, car, 51999).context['cars'][0]['mileage_form'].errors


@pytest.mark.parametrize('return_to', ['https://example.com', '//example.com', '/accounts/', '', 'Garage'])
def test_unrecognized_return_destination_keeps_vehicle_flow(browser, car, return_to):
    response = browser.post(reverse('reading-add', args=[car.pk]),
                            {'mode': 'quick', 'miles': 51000, 'return_to': return_to, 'view': 'list'})
    assert response.url == reverse('vehicle-detail', args=[car.pk]) + '?view=list'


def test_dashboard_save_ownership_and_csrf(browser, car):
    other, _ = account_client('other-dashboard')
    other.get('/accounts/welcome/')
    assert save(other, car, 51000).status_code == 404
    assert save(Client(), car, 51000).status_code == 302
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(car.garage.owner, backend='allauth.account.auth_backends.AuthenticationBackend')
    assert save(csrf, car, 51000).status_code == 403
    assert car.readings.count() == 1
