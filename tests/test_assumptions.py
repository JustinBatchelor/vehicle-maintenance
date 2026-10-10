from datetime import date
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from garage.calculator import Baseline, Rule, Service, calculate
from garage.models import Vehicle, VehicleConfiguration, MaintenanceItem, OdometerReading
from garage.services import recommendations

TODAY = date(2026, 10, 9)


def assumed(rule, **overrides):
    params = dict(today=TODAY, miles=133600, in_service=None, services=[],
                  baseline=Baseline(TODAY, 133600))
    params.update(overrides)
    return calculate(rule, **params)


@pytest.mark.parametrize('miles,target,status', [(133600,135000,'upcoming'), (134600,135000,'due-soon'), (135000,142500,'upcoming')])
def test_assumption_uses_next_scheduled_milestone_not_full_interval_from_setup(miles,target,status):
    result = assumed(Rule(miles=7500, months=6, basis='service'), miles=miles, baseline=Baseline(TODAY,miles))
    assert (result.miles,result.status,result.date) == (target,status,date(2027,4,9))
    assert 'assumed complete' in result.reason and 'time intervals start' in result.reason


def test_assumption_remains_fixed_as_odometer_and_calendar_advance():
    result = assumed(Rule(miles=7500,months=6,basis='service'), miles=136000, today=date(2027,5,1))
    assert result.miles == 135000 and result.date == date(2027,4,9) and result.status == 'overdue'


def test_assumption_preserves_first_then_recurring_limits():
    rule = Rule(miles=75000,months=72,first_miles=137500,first_months=132,basis='service')
    before = assumed(rule, miles=50000, baseline=Baseline(TODAY,50000), in_service=date(2021,1,1))
    assert before.miles == 137500 and before.date == date(2032,1,1)
    after = assumed(rule, miles=140000, baseline=Baseline(TODAY,140000), in_service=date(2010,1,1))
    assert after.miles == 212500 and after.date == date(2027,1,1)


def test_assumed_date_milestone_respects_anniversary_day():
    rule = Rule(months=6)
    before = assumed(rule, in_service=date(2020,10,10))
    assert before.date == date(2026,10,10) and before.status == 'due-soon'
    on = assumed(rule, in_service=date(2020,10,9))
    assert on.date == date(2027,4,9)


def test_real_backdated_work_and_never_serviced_override_assumption():
    rule = Rule(miles=6000,basis='service')
    actual = assumed(rule,miles=50000,services=[Service(date(2026,7,1),45000)],baseline=Baseline(TODAY,50000))
    assert actual.miles == 51000 and 'assumed' not in actual.reason
    original = assumed(rule,never_serviced=True)
    assert original.miles == 6000 and original.status == 'overdue'


def test_assumption_does_not_invent_conditional_or_engine_hour_history():
    assert assumed(Rule(basis='conditional')).status == 'as-needed'
    rule = Rule(miles=5000,hours=200,basis='service')
    assert assumed(rule).status == 'unknown'
    result = assumed(rule,engine_hours=1150,baseline=Baseline(TODAY,133600,1150))
    assert result.remaining_hours == 50 and result.status == 'upcoming'


def test_future_assumption_is_not_applied():
    assert assumed(Rule(miles=7500),baseline=Baseline(date(2027,1,1),133600)).status == 'unknown'


def row(car,key='oil'):
    with patch('garage.services.timezone.localdate',return_value=TODAY):
        return next(r for r in recommendations(car) if r['item'].key==key)


def test_new_vehicle_defaults_to_assumed_history_without_fabricating_records(browser):
    assert browser.get('/vehicles/new/').context['form']['assume_maintained'].value() is True
    config=VehicleConfiguration.objects.get(key='nissan-altima-2012-cvt')
    response=browser.post('/vehicles/new/',{'configuration':config.pk,'initial_miles':133600,'reading_date':TODAY,'assume_maintained':'on'})
    assert response.status_code==302
    car=Vehicle.objects.get(configuration=config)
    assert car.assumed_through_date==TODAY and car.assumed_through_miles==133600
    assert row(car)['due'].miles==135000 and row(car)['due'].status=='upcoming'
    assert not car.records.exists()
    assert len(browser.get(reverse('history-csv',args=[car.pk])).content.decode().splitlines())==1


def test_setup_opt_out_retains_unknown_history(browser):
    config=VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited')
    browser.post('/vehicles/new/',{'configuration':config.pk,'initial_miles':50000,'reading_date':TODAY})
    car=Vehicle.objects.get(configuration=config)
    assert car.assumed_through_date is None and row(car)['due'].status=='unknown'


def test_existing_vehicle_can_enable_preserve_and_remove_assumption(browser,car):
    path=reverse('vehicle-edit',args=[car.pk]);data={'configuration':car.configuration_id,'assume_maintained':'on'}
    assert browser.get(path).context['form']['assume_maintained'].value() is False
    assert browser.post(path,data).status_code==302
    car.refresh_from_db();assert car.assumed_through_miles==50000 and row(car)['due'].miles==54000
    OdometerReading.objects.create(vehicle=car,miles=55000,date=TODAY)
    browser.post(path,data);car.refresh_from_db()
    assert car.assumed_through_miles==50000 and row(car)['due'].status=='overdue'
    browser.post(path,{'configuration':car.configuration_id});car.refresh_from_db()
    assert car.assumed_through_date is None and row(car)['due'].status=='unknown'


def test_item_choices_override_assumption_and_can_be_reverted(browser,car):
    browser.post(reverse('vehicle-edit',args=[car.pk]),{'configuration':car.configuration_id,'assume_maintained':'on'})
    car.refresh_from_db();item=MaintenanceItem.objects.get(key='oil');path=reverse('original',args=[car.pk,item.pk])
    browser.post(path,{'clear':'1'});assert row(car)['due'].status=='unknown'
    browser.post(path,{});assert row(car)['due'].miles==6000
    browser.post(path,{'assume':'1'});assert row(car)['due'].miles==54000
    record_url=reverse('record-add',args=[car.pk])
    browser.post(record_url,{'item':item.pk,'date':'2026-07-01','miles':45000})
    assert row(car)['due'].miles==51000
    record=car.records.get();browser.post(reverse('record-delete',args=[car.pk,record.pk]))
    assert row(car)['due'].miles==54000


def test_assumption_obeys_conditions_and_ownership(browser,car):
    other=Client();other.post('/start/')
    path=reverse('vehicle-edit',args=[car.pk])
    data={'configuration':car.configuration_id,'conditions':['towing'],'assume_maintained':'on'}
    assert other.post(path,data).status_code==404
    car.refresh_from_db();assert car.assumed_through_date is None
    assert browser.post(path,data).status_code==302
    car.refresh_from_db();assert row(car)['due'].miles==51000
