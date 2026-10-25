from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.urls import reverse

from conftest import account_client
from garage.mileage import update_current_mileage
from garage.models import Appointment, MaintenanceItem, OdometerReading, ServiceRecord
from garage.services import recommendations


@pytest.fixture(autouse=True)
def fixed_today():
    with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 25, 16, tzinfo=dt_timezone.utc)):
        yield


def endpoint(car):
    return reverse('reading-add', args=[car.pk])


def quick(miles, view='timeline', **kwargs):
    return {'mode': 'quick', 'miles': miles, 'view': view, **kwargs}


@pytest.mark.parametrize('view', ['timeline', 'list'])
def test_prefill_and_save_in_both_views(browser, car, view):
    detail = reverse('vehicle-detail', args=[car.pk])
    response = browser.get(detail, {'view': view})
    assert response.context['mileage_form'].initial['miles'] == 50000
    assert b'Save mileage' in response.content
    response = browser.post(endpoint(car), quick(51000, view))
    assert response.url == detail + ('?view=list' if view == 'list' else '')
    reading = car.readings.order_by('-id').first()
    assert (reading.date, reading.miles, reading.engine_hours) == (date(2026, 10, 25), 51000, None)
    assert not car.records.exists()


@pytest.mark.parametrize('miles,status', [(53000, 'upcoming'), (53500, 'due-soon'), (54000, 'due'), (54001, 'overdue')])
def test_recalculates_without_advancing_service_or_assumption(browser, car, miles, status):
    car.in_service_date = date(2026, 10, 1)
    car.assumed_through_date = date(2026, 10, 1)
    car.assumed_through_miles = 50000
    car.save()
    oil = MaintenanceItem.objects.get(key='oil')
    ServiceRecord.objects.create(vehicle=car, item=oil, date=date(2026, 10, 1), miles=48000)
    appointment = Appointment.objects.create(vehicle=car, title='Upcoming service', date=date(2026, 11, 1))
    before = {r['item'].key: (r['due'].miles, r['due'].date) for r in recommendations(car)}
    response = browser.post(endpoint(car), quick(miles), follow=True)
    assert response.status_code == 200
    after = {r['item'].key: r['due'] for r in response.context['rows']}
    assert after['oil'].status == status and after['oil'].remaining_miles == 54000 - miles
    assert {key: (due.miles, due.date) for key, due in after.items()} == before
    assert any(p['current'] and p['miles'] == miles for p in response.context['timeline']['milestones'])
    car.refresh_from_db()
    assert car.assumed_through_miles == 50000 and car.records.count() == 1
    assert Appointment.objects.filter(pk=appointment.pk).exists()
    home = browser.get(reverse('home'))
    if status in home.context['counts']:
        assert home.context['counts'][status] > 0


@pytest.mark.parametrize('miles', [-1, 3000001, 'bad', '1.5', '', 49999])
def test_invalid_mileage_keeps_inline_errors_and_view(browser, car, miles):
    response = browser.post(endpoint(car), quick(miles, 'list'))
    assert response.status_code == 200 and response.context['maintenance_view'] == 'list'
    assert response.context['mileage_form'].errors
    assert response.context['mileage_form'].data['miles'] == str(miles)
    assert car.readings.count() == 1 and not car.records.exists()


def test_today_is_server_owned_and_uses_garage_timezone(browser, car):
    with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 26, 1, tzinfo=dt_timezone.utc)):
        response = browser.post(endpoint(car), quick(51000, date='2099-01-01', engine_hours=999))
    assert response.status_code == 302
    reading = car.readings.order_by('-id').first()
    assert reading.date == date(2026, 10, 25) and reading.engine_hours is None


def test_same_day_service_and_reading_decreases_rejected(browser, car):
    oil = MaintenanceItem.objects.get(key='oil')
    ServiceRecord.objects.create(vehicle=car, item=oil, date=date(2026, 10, 25), miles=51000)
    response = browser.post(endpoint(car), quick(50500))
    assert 'latest reading or service' in str(response.context['mileage_form'].errors)
    assert browser.post(endpoint(car), quick(52000)).status_code == 302
    assert browser.post(endpoint(car), quick(51999)).context['mileage_form'].errors
    assert car.latest_reading.miles == 52000


def test_duplicate_today_is_noop_but_later_day_records_new_observation(browser, car):
    assert browser.post(endpoint(car), quick(51000)).status_code == 302
    assert browser.post(endpoint(car), quick(51000)).status_code == 302
    assert car.readings.count() == 2
    assert browser.post(endpoint(car), quick(52000)).status_code == 302
    assert browser.post(endpoint(car), quick(51000)).status_code == 302
    assert car.readings.count() == 3 and car.latest_reading.miles == 52000
    with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 26, 16, tzinfo=dt_timezone.utc)):
        assert browser.post(endpoint(car), quick(52000)).status_code == 302
    assert car.readings.count() == 4


def test_does_not_carry_old_hours_and_preserves_unknown_history(browser, car):
    car.readings.update(engine_hours=1000)
    assert browser.post(endpoint(car), quick(50010)).status_code == 302
    assert car.latest_reading.engine_hours is None
    assert all(r['due'].unknown or r['due'].status == 'as-needed' for r in recommendations(car))


def test_first_reading_and_future_in_service(browser, car):
    car.readings.all().delete()
    page = browser.get(reverse('vehicle-detail', args=[car.pk]))
    assert page.context['mileage_form'].initial['miles'] is None
    assert browser.post(endpoint(car), quick(0)).status_code == 302
    car.in_service_date = date(2026, 11, 1)
    car.save()
    response = browser.post(endpoint(car), quick(1))
    assert response.context['mileage_form'].errors


def test_ownership_csrf_and_methods(browser, car):
    other, _ = account_client('other-mileage')
    other.get('/accounts/welcome/')
    assert other.post(endpoint(car), quick(51000)).status_code == 404
    assert Client().post(endpoint(car), quick(51000)).status_code == 302
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(car.garage.owner, backend='allauth.account.auth_backends.AuthenticationBackend')
    assert csrf.post(endpoint(car), quick(51000)).status_code == 403
    assert browser.put(endpoint(car), quick(51000)).status_code == 405
    assert car.readings.count() == 1


def test_full_form_retains_historical_readings_and_corrections(browser, car):
    assert browser.post(endpoint(car), {'date': '2026-09-01', 'miles': 49000, 'engine_hours': 1000}).status_code == 302
    old = car.readings.get(date=date(2026, 9, 1))
    assert old.engine_hours == 1000 and car.latest_reading.miles == 50000
    response = browser.post(reverse('reading-edit', args=[car.pk, old.pk]), {'date': '2026-09-01', 'miles': 48000})
    assert response.status_code == 302
    assert browser.post(endpoint(car), {'date': '2099-01-01', 'miles': 80000}).context['form'].errors
    assert browser.post(endpoint(car), {'date': '2026-09-15', 'miles': 60000}).context['form'].errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('values', [(51000, 51000), (51000, 52000)])
def test_concurrent_updates_are_serialized(car, values):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    barrier = Barrier(2)
    def save(miles):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return update_current_mileage(car, miles)[1]
            except ValidationError:
                return 'rejected'
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, values))
    assert car.latest_reading.miles == max(values)
    assert car.readings.filter(miles=max(values)).count() == 1
    if values[0] == values[1]:
        assert sorted(results) == [False, True]
    else:
        assert results[1] is True and results[0] in [True, 'rejected']
