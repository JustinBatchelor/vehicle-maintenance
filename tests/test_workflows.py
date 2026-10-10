import csv
import io
import json
from datetime import date
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch
import pytest
from django.core.management import call_command,CommandError
from django.test import Client
from django.urls import reverse
from garage.models import Garage,Vehicle,VehicleConfiguration,ServiceRecord,MaintenanceItem,MaintenanceRule,Appointment
from garage.services import applicable_rules,recommendations
from garage.forms import VehicleForm,RecordForm
from icalendar import Calendar
from conftest import account_client

def test_start_is_explicit_and_private(catalog,settings):
    settings.GOOGLE_AUTH_REQUIRED=False
    c=Client()
    assert c.get('/').status_code==200 and Garage.objects.count()==0
    assert c.get('/start/').status_code==405
    assert c.post('/start/').status_code==302
    assert c.session.get('garage_id') and Garage.objects.count()==1
    assert c.post('/start/').status_code==302 and Garage.objects.count()==1

def test_csrf(catalog):
    c=Client(enforce_csrf_checks=True)
    assert c.post('/start/').status_code==403

def test_cookie_recovery(catalog,settings):
    settings.GOOGLE_AUTH_REQUIRED=False
    browser=Client();browser.post('/start/')
    garage=Garage.objects.get()
    response=browser.post('/settings/',{'action':'recovery'})
    code=response.context['code'];garage.refresh_from_db()
    assert code and code!=garage.recovery_hash
    other=Client();assert other.post('/recover/',{'code':code}).status_code==302
    assert other.session['garage_id']==str(garage.pk)
    assert 'no-store' in response['Cache-Control']


def test_cross_garage_isolation(browser,car):
    other,user=account_client('other');other.get('/accounts/welcome/')
    paths=[reverse('vehicle-detail',args=[car.pk]),reverse('vehicle-edit',args=[car.pk]),reverse('history-csv',args=[car.pk]),reverse('vehicle-delete',args=[car.pk])]
    for path in paths:assert other.get(path).status_code==404
    assert other.post(paths[-1]).status_code==404 and Vehicle.objects.filter(pk=car.pk).exists()

def test_vehicle_create_form(browser):
    response=browser.get('/vehicles/new/')
    assert response.status_code==200 and 'initial_miles' in response.context['form'].fields
    c=VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited')
    response=browser.post('/vehicles/new/',{'configuration':c.pk,'nickname':'Trail car','initial_miles':30000,'reading_date':'2026-10-01','conditions':['towing'],'equipment':[]})
    assert response.status_code==302
    car=Vehicle.objects.get(nickname='Trail car')
    assert car.latest_reading.miles==30000 and car.conditions==['towing']

def test_invalid_configuration_and_conditions(garage):
    form=VehicleForm({'configuration':'not-a-number','initial_miles':1,'reading_date':'2026-01-01'})
    assert not form.is_valid()

def test_history_edits_and_deletion(browser,car):
    item=MaintenanceItem.objects.get(key='oil')
    path=reverse('record-add',args=[car.pk])
    r=browser.post(path,{'item':item.pk,'date':'2026-07-01','miles':45000,'cost':'40.50','notes':'DIY'})
    assert r.status_code==302
    record=car.records.get();assert record.cost==__import__('decimal').Decimal('40.50')
    row=next(r for r in recommendations(car) if r['item'].pk==item.pk)
    assert row['due'].miles==51000
    r=browser.post(reverse('record-edit',args=[car.pk,record.pk]),{'item':item.pk,'date':'2026-07-02','miles':45500})
    assert r.status_code==302
    browser.post(reverse('record-delete',args=[car.pk,record.pk]))
    assert next(r for r in recommendations(car) if r['item'].pk==item.pk)['due'].status=='unknown'

def test_future_and_conflicting_records_rejected(car):
    item=MaintenanceItem.objects.get(key='oil')
    for data in [{'item':item.pk,'date':'2099-01-01','miles':60000},{'item':item.pk,'date':'2026-01-01','miles':80000}]:
        assert not RecordForm(data,vehicle=car).is_valid()

def test_service_record_can_be_latest_observation(car):
    item=MaintenanceItem.objects.get(key='oil')
    ServiceRecord.objects.create(vehicle=car,item=item,date=date(2026,10,2),miles=50500)
    assert car.latest_reading.miles==50500

def test_calendar_and_csv(browser,car):
    item=MaintenanceItem.objects.get(key='oil')
    a=Appointment.objects.create(vehicle=car,date=date(2026,12,31),title='Oil change',notes='Private notes')
    a.items.add(item)
    response=browser.get(reverse('appointment-detail',args=[car.pk,a.pk]))
    assert response.status_code==200
    query=parse_qs(urlparse(response.context['google_url']).query)
    assert query['dates']==['20261231/20270101'] and 'Private notes' not in query['details'][0]
    event=Calendar.from_ical(browser.get(reverse('calendar-download',args=[car.pk,a.pk])).content).walk('vevent')[0]
    assert event.decoded('dtstart')==date(2026,12,31) and event.decoded('dtend')==date(2027,1,1)
    assert car.records.count()==0
    ServiceRecord.objects.create(vehicle=car,item=item,date=date(2026,1,1),miles=10000,provider='=DANGEROUS()',notes='one, two\nthree')
    csv_response=browser.get(reverse('history-csv',args=[car.pk]))
    rows=list(csv.reader(io.StringIO(csv_response.content.decode())))
    assert rows[1][6].startswith("'=") and rows[1][7]=='one, two\nthree'
    other,user=account_client('other');other.get('/accounts/welcome/')
    assert other.get(reverse('calendar-download',args=[car.pk,a.pk])).status_code==404

def test_never_serviced_is_not_completed_work(browser,car):
    item=MaintenanceItem.objects.get(key='coolant')
    browser.post(reverse('original',args=[car.pk,item.pk]))
    result=next(r for r in recommendations(car) if r['item'].pk==item.pk)['due']
    assert result.miles==137500 and not car.records.exists()

def test_templates_render(browser,car):
    for name,args in [('home',[]),('vehicle-detail',[car.pk]),('vehicle-edit',[car.pk]),('record-add',[car.pk]),('reading-add',[car.pk]),('appointment-add',[car.pk]),('garage-settings',[])]:
        assert browser.get(reverse(name,args=args)).status_code==200

def test_import_idempotent_and_atomic(catalog,tmp_path):
    before=MaintenanceRule.objects.count();call_command('import_schedules',verbosity=0)
    assert MaintenanceRule.objects.count()==before
    from django.conf import settings
    data=json.loads((settings.BASE_DIR/'data/schedules.json').read_text())
    data['schedules'][0]['rules'][0]['miles']=-1
    p=tmp_path/'bad.json';p.write_text(json.dumps(data))
    with pytest.raises(CommandError):call_command('import_schedules',str(p))
    assert MaintenanceRule.objects.count()==before

def test_manufacturer_specific_rules(car):
    car.conditions=['towing','humidity']
    rules={r.item.key:r for r in applicable_rules(car)}
    assert rules['oil'].miles==3000 and rules['cvt-replace'].miles==24855
    assert rules['brake-fluid'].miles==15000 and rules['brake-fluid-check'].miles==6000
    car.configuration=VehicleConfiguration.objects.get(key='ford-f150-2010-4x4');car.conditions=['towing']
    rules={r.item.key:r for r in applicable_rules(car)}
    assert rules['at-fluid'].miles==150000 and rules['transfer'].miles==60000
    assert 'fuel-filter' not in rules and 'cabin' not in rules
    car.configuration=VehicleConfiguration.objects.get(key='nissan-altima-2012-cvt');car.conditions=['towing']
    rules={r.item.key:r for r in applicable_rules(car)}
    assert rules['oil'].miles==3750 and rules['cvt-replace'].basis=='conditional'
    assert 'diff' not in rules and rules['plugs'].miles==105000
