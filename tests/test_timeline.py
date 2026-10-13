from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from conftest import account_client
from garage.calculator import Due
from garage.completions import complete_services
from garage.forms import CompletionForm
from garage.models import CompletionSubmission, MaintenanceItem, ServiceRecord
from garage.services import maintenance_timeline, recommendations


def row(item_id, due, optional=False):
    return {"item": SimpleNamespace(pk=item_id, name=str(item_id)),
            "rule": SimpleNamespace(optional=optional), "due": due}


def test_exact_milestones_current_marker_and_optional_order():
    rows = [row(1, Due('overdue', miles=75000, remaining_days=-10)),
            row(2, Due('upcoming', miles=60000), optional=True),
            row(3, Due('upcoming', miles=60000)), row(4, Due('due', miles=50000)),
            row(5, Due('overdue', miles=24855))]
    timeline = maintenance_timeline(rows, SimpleNamespace(miles=50000))
    assert [point['miles'] for point in timeline['milestones']] == [24855, 50000, 60000, 75000]
    assert [point['current'] for point in timeline['milestones']] == [False, True, False, False]
    assert [r['item'].pk for r in timeline['milestones'][2]['rows']] == [3, 2]
    assert rows[0] in timeline['attention']  # Calendar-overdue work stays at 75,000.
    assert sum(len(point['rows']) for point in timeline['milestones']) == len(rows)


def test_non_mileage_sections_and_partial_unknown_deadline():
    rows = [row(1, Due('unknown', date=date(2026,10,30), remaining_days=10, unknown=True)),
            row(2, Due('upcoming', remaining_hours=100)), row(3, Due('unknown', unknown=True)),
            row(4, Due('as-needed'))]
    timeline = maintenance_timeline(rows, None)
    assert not timeline['milestones']
    assert [len(section['rows']) for section in timeline['sections']] == [2, 1, 1]
    assert timeline['attention'] == [rows[0]]


@pytest.fixture
def selection(car):
    items = list(MaintenanceItem.objects.filter(key__in=['oil', 'tires']).order_by('pk'))
    assert len(items) == 2
    return items


def payload(selected_items, **overrides):
    return {'items': [item.pk for item in selected_items], 'date': timezone.localdate().isoformat(),
            'miles': 50500, 'token': str(uuid.uuid4()), **overrides}


def endpoint(car):
    return reverse('service-complete', args=[car.pk])


def test_default_timeline_and_secondary_list(browser, car):
    response = browser.get(reverse('vehicle-detail', args=[car.pk]))
    assert response.context['maintenance_view'] == 'timeline'
    assert b'Maintenance timeline' in response.content and b'Current mileage' in response.content
    response = browser.get(reverse('vehicle-detail', args=[car.pk]), {'view': 'list'})
    assert b'id="status-filter"' in response.content
    assert b'Maintenance schedule' in response.content


def test_get_only_prefills_and_does_not_save(browser, car, selection):
    response = browser.get(endpoint(car), {'items': [i.pk for i in selection]})
    form = response.context['form']
    assert form.initial['miles'] == 50000
    assert form.initial['date'] == timezone.localdate()
    assert len(response.context['selected']) == 2
    assert not car.records.exists() and not CompletionSubmission.objects.exists()
    assert browser.get(endpoint(car)).context['selection_error']
    assert browser.get(endpoint(car), {'items': 'invalid'}).context['selection_error']


def test_single_and_batch_save_refresh_history_and_csv(browser, car, selection):
    data = payload(selection)
    response = browser.post(endpoint(car), data, HTTP_HX_REQUEST='true')
    assert response['HX-Redirect'] == reverse('vehicle-detail', args=[car.pk])
    assert car.records.count() == 2 and car.readings.count() == 1
    assert car.latest_reading.miles == 50500
    receipt = CompletionSubmission.objects.get()
    assert receipt.records.count() == 2
    for record in receipt.records.all():
        assert record.cost is None and record.provider == record.notes == ''
    csv = browser.get(reverse('history-csv', args=[car.pk])).content.decode()
    assert all(item.name in csv for item in selection)
    assert browser.post(endpoint(car), payload(selection[:1], miles=51000)).status_code == 302
    assert car.records.count() == 3


def test_retry_and_changed_payload(browser, car, selection):
    data = payload(selection)
    assert browser.post(endpoint(car), data).status_code == 302
    assert browser.post(endpoint(car), data).status_code == 302
    assert car.records.count() == 2
    # Order and duplicate selected IDs do not change the logical submission.
    data['items'] = list(reversed(data['items'])) + data['items'][:1]
    assert browser.post(endpoint(car), data).status_code == 302
    response = browser.post(endpoint(car), {**data, 'miles': 51000})
    assert 'different details' in str(response.context['form'].errors)
    assert car.records.count() == 2
    car.records.all().delete()
    assert browser.post(endpoint(car), data).status_code == 302
    assert not car.records.exists()  # Receipts survive deletion; retry is not an undo.


@pytest.mark.parametrize('overrides', [
    {'miles': -1}, {'miles': 40000}, {'miles': 'no'}, {'date': '2099-01-01'},
    {'date': '2020-01-01'}, {'items': []}, {'items': [999999]}, {'token': 'invalid'}])
def test_invalid_completion_preserves_input_and_writes_nothing(browser, car, selection, overrides):
    data = payload(selection, **overrides)
    response = browser.post(endpoint(car), data, HTTP_HX_REQUEST='true')
    assert response.status_code == 200 and response.context['form'].errors
    assert response.context['form'].data['miles'] == str(data['miles'])
    assert not car.records.exists() and not CompletionSubmission.objects.exists()
    assert b'<html' not in response.content


def test_backdating_early_work_and_recalculation(browser, car):
    oil = MaintenanceItem.objects.get(key='oil')
    before = {r['item'].pk: r['due'] for r in recommendations(car)}
    data = payload([oil], date='2026-07-01', miles=45000)
    browser.post(endpoint(car), data)
    after = {r['item'].pk: r['due'] for r in recommendations(car)}
    assert after[oil.pk].miles == 51000
    assert all(after[key] == value for key, value in before.items() if key != oil.pk)
    assert car.latest_reading.miles == 50000
    record = car.records.get()
    browser.post(reverse('record-edit', args=[car.pk, record.pk]), {'item': oil.pk, 'date': '2026-07-02', 'miles': 46000})
    assert next(r['due'].miles for r in recommendations(car) if r['item'].pk == oil.pk) == 52000
    browser.post(reverse('record-delete', args=[car.pk, record.pk]))
    assert next(r['due'].status for r in recommendations(car) if r['item'].pk == oil.pk) == 'unknown'


def test_assumption_is_not_advanced_by_completion(browser, car):
    car.assumed_through_date = date(2026, 10, 1)
    car.assumed_through_miles = 50000
    car.save()
    before = {r['item'].pk: r['due'].miles for r in recommendations(car)}
    oil = MaintenanceItem.objects.get(key='oil')
    assert before[oil.pk] == 54000
    browser.post(endpoint(car), payload([oil], miles=51000))
    car.refresh_from_db()
    after = {r['item'].pk: r['due'].miles for r in recommendations(car)}
    assert after[oil.pk] == 57000  # Early actual work resets a service-based rule.
    assert car.assumed_through_miles == 50000
    assert all(after[key] == value for key, value in before.items() if key != oil.pk)


def test_atomic_failure(car, selection):
    form = CompletionForm(payload(selection), vehicle=car)
    assert form.is_valid()
    create = ServiceRecord.objects.create
    calls = []
    def fail_second(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError('synthetic write failure')
        return create(**kwargs)
    with patch('garage.completions.ServiceRecord.objects.create', side_effect=fail_second):
        with pytest.raises(RuntimeError):
            complete_services(car, form.cleaned_data)
    assert not car.records.exists() and not CompletionSubmission.objects.exists()


def test_isolation_csrf_and_methods(browser, car, selection):
    other, _ = account_client('other-completion')
    other.get('/accounts/welcome/')
    assert other.get(endpoint(car)).status_code == 404
    assert other.post(endpoint(car), payload(selection)).status_code == 404
    csrf = Client(enforce_csrf_checks=True)
    csrf.force_login(car.garage.owner, backend='allauth.account.auth_backends.AuthenticationBackend')
    assert csrf.post(endpoint(car), payload(selection)).status_code == 403
    assert browser.put(endpoint(car)).status_code == 405
    assert not car.records.exists()


def test_optional_engine_hours(browser, car):
    from garage.models import VehicleConfiguration
    car.configuration = VehicleConfiguration.objects.get(key='ford-f150-2010-4x4')
    # Find the reviewed engine-hour condition instead of assuming a label.
    from garage.models import MaintenanceRule
    rule = MaintenanceRule.objects.filter(schedule=car.configuration.schedule, hours__isnull=False).first()
    car.conditions = rule.conditions_any
    car.save()
    data = payload([rule.item], engine_hours=1500)
    assert browser.post(endpoint(car), data).status_code == 302
    assert car.records.get().engine_hours == 1500
    assert browser.post(endpoint(car), payload([rule.item], miles=51000)).status_code == 302
    assert car.records.order_by('-miles').first().engine_hours is None
    assert next(r['due'].unknown for r in recommendations(car) if r['item'].pk == rule.item_id)
    invalid = browser.post(endpoint(car), payload([rule.item], engine_hours=2147483648))
    assert 'engine_hours' in invalid.context['form'].errors
    tire = MaintenanceItem.objects.get(key='tires')
    assert 'engine_hours' not in browser.get(endpoint(car), {'items': tire.pk}).context['form'].fields


def test_default_date_uses_garage_timezone(browser, car, selection):
    from datetime import datetime, timezone as dt_timezone
    with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 13, 1, tzinfo=dt_timezone.utc)):
        response = browser.get(endpoint(car), {'items': selection[0].pk})
        assert response.context['form'].initial['date'] == date(2026, 10, 12)


def test_applicability_rechecked_inside_transaction(car, selection):
    from django.core.exceptions import ValidationError
    form = CompletionForm(payload(selection), vehicle=car)
    assert form.is_valid()
    with patch('garage.completions.applicable_rules', return_value=[]):
        with pytest.raises(ValidationError):
            complete_services(car, form.cleaned_data)
    assert not car.records.exists() and not CompletionSubmission.objects.exists()


def test_receipt_cannot_be_reused_on_another_vehicle(browser, car, selection):
    from garage.models import Vehicle
    data = payload(selection)
    assert browser.post(endpoint(car), data).status_code == 302
    other = Vehicle.objects.create(garage=car.garage, configuration=car.configuration)
    response = browser.post(endpoint(other), data)
    assert 'different details' in str(response.context['form'].errors)
    assert not other.records.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_create_one_batch(car, selection):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    form = CompletionForm(payload(selection), vehicle=car)
    assert form.is_valid()
    barrier = Barrier(2)
    def save(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return complete_services(car, form.cleaned_data)[1]
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, range(2))) == [False, True]
    assert car.records.count() == 2 and CompletionSubmission.objects.count() == 1
