from dataclasses import fields
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from django.core.management import call_command
from django.urls import reverse

from garage.calculator import Baseline, Rule, Service, calculate
from garage.models import MaintenanceItem, MaintenanceRule, VehicleConfiguration
from garage.services import applicable_rules
from garage.videos import candidate_matches, discover, queries


@pytest.fixture
def ascent(car):
    car.configuration = VehicleConfiguration.objects.get(key='subaru-ascent-2026-limited')
    car.in_service_date = date(2026, 10, 1)
    car.save()
    return car


def test_catalog_keeps_all_previous_data_and_is_reproducible(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root/'data/schedules.json').read_text())
    previous = {**data,
                'sources': [s for s in data['sources'] if s['key'] != 'subaru-2026'],
                'schedules': [s for s in data['schedules'] if s['key'] != 'ascent-2026'],
                'configurations': [c for c in data['configurations'] if c['key'] != 'subaru-ascent-2026-limited']}
    # Entire published 2026.10.09.2 catalog, before adding the new model.
    assert hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest() == 'e8734b9a866cb60a1b2a89053d45d2583ad3ae3aa3791364c203693a3fb7bb30'
    (tmp_path/'scripts').mkdir()
    (tmp_path/'data').mkdir()
    shutil.copy(root/'scripts/build_catalog.py', tmp_path/'scripts/build_catalog.py')
    subprocess.run([sys.executable, str(tmp_path/'scripts/build_catalog.py')], check=True)
    assert (tmp_path/'data/schedules.json').read_bytes() == (root/'data/schedules.json').read_bytes()


def test_ascent_review_and_normal_table(ascent):
    c = ascent.configuration
    assert (c.engine, c.transmission, c.drivetrain) == ('2.4L turbo flat-four', 'CVT', 'AWD')
    assert c.condition_options == {} and c.equipment_options == {}
    assert c.schedule.version == '2026.10.25.1' and c.schedule.reviewed
    assert c.schedule.reviewed_on == date(2026, 10, 25)
    assert c.schedule.source.sha256 == 'efefdeb029aa8310e2a5626c0a2eb018136681e3b8b6044ae38ba6a0d9e00e82'
    assert '051925.pdf' in c.schedule.source.publication
    assert c.schedule.source.url == 'https://www.subaru.com/owners/vehicle-resources.html?model=2026-ASC-TCL'
    expected = {
        'oil': (6000, 6), 'tires': (6000, 6), 'plugs': (60000, 60),
        'belts': (30000, 30), 'air': (30000, 30), 'cooling': (30000, 30),
        'diff': (30000, 30), 'brake-fluid': (30000, 30), 'fuel-lines': (30000, 30),
        'cvt': (36000, 36), 'fuel-filter': (72000, 72), 'coolant': (75000, 72),
        'brake-lines': (12000, 12), 'brakes': (12000, 12), 'boots': (12000, 12),
        'steering': (12000, 12), 'wheel-bearing': (60000, 60), 'cabin': (12000, 12),
    }
    rules = {r.item.key: r for r in applicable_rules(ascent)}
    assert {key: (r.miles, r.months) for key, r in rules.items()} == expected
    assert all(r.page == 28 and not r.optional and not r.conditions_any for r in rules.values())
    assert rules['cvt'].item.action == rules['diff'].item.action == 'inspect'
    assert rules['brake-fluid'].item.action == 'replace'
    assert (rules['coolant'].first_miles, rules['coolant'].first_months) == (137500, 132)
    before = list(MaintenanceRule.objects.values_list('id', flat=True))
    call_command('import_schedules', verbosity=0)
    assert list(MaintenanceRule.objects.values_list('id', flat=True)) == before


def test_ascent_initial_and_subsequent_targets(ascent):
    rules = {r.item.key: Rule(**{f.name: getattr(r, f.name) for f in fields(Rule)}) for r in applicable_rules(ascent)}
    params = dict(today=date(2026, 10, 25), miles=120, in_service=date(2026, 10, 1), services=[],
                  baseline=Baseline(date(2026, 10, 1), 12))
    oil = calculate(rules['oil'], **params)
    assert (oil.miles, oil.date, oil.status) == (6000, date(2027, 4, 1), 'upcoming')
    cvt = calculate(rules['cvt'], **params)
    assert (cvt.miles, cvt.date) == (36000, date(2029, 10, 1))
    coolant = calculate(rules['coolant'], **params)
    assert (coolant.miles, coolant.date) == (137500, date(2037, 10, 1))
    assert calculate(rules['oil'], **{**params, 'today': date(2027, 4, 2)}).status == 'overdue'
    assert calculate(rules['oil'], **{**params, 'miles': 6001}).status == 'overdue'
    later = calculate(rules['coolant'], **{**params, 'today': date(2037, 10, 2), 'miles': 137500,
                      'services': [Service(date(2037, 10, 1), 137500)]})
    assert (later.miles, later.date) == (212500, date(2043, 10, 1))


def test_ascent_setup_and_unreviewed_conditions(browser, ascent):
    response = browser.get(reverse('vehicle-add'))
    assert any(c['id'] == ascent.configuration_id for c in response.context['catalog'])
    data = {'configuration': ascent.configuration_id, 'initial_miles': 120, 'reading_date': '2026-10-25',
            'in_service_date': '2026-10-01', 'assume_maintained': 'on'}
    invalid = browser.post(reverse('vehicle-add'), {**data, 'conditions': ['towing']})
    assert 'conditions' in invalid.context['form'].errors
    saved = browser.post(reverse('vehicle-add'), data)
    assert saved.status_code == 302
    created = ascent.garage.vehicles.exclude(pk=ascent.pk).get()
    assert created.configuration_id == ascent.configuration_id
    assert created.latest_reading.miles == 120 and not created.records.exists()


@pytest.mark.parametrize('title,match', [
    ('2026 Subaru Ascent 2.4L turbo oil and filter change', True),
    ('2019–2026 Ascent 2.4L oil change tutorial', True),
    ('2025 Subaru Ascent 2.4L oil change', False),
    ('2026 Subaru Crosstrek 2.5L oil change', False),
    ('2026 Subaru Ascent Outback 2.4L oil change', False),
    ('2026 Subaru Ascent 2.5L oil change', False),
    ('2026 Subaru Ascent 2.4L naturally aspirated oil change', False),
    ('2026 Subaru Ascent 2.4L non-turbo oil change', False),
    ('2026 Subaru Ascent 2.4L manual transmission oil change', False),
    ('2026 Subaru Ascent 2.4L FWD oil change', False),
])
def test_ascent_video_matching(ascent, title, match):
    video = {'snippet': {'title': title, 'description': ''}}
    assert candidate_matches(video, ascent, MaintenanceItem.objects.get(key='oil')) == match


def test_ascent_search_fallback_and_other_model_conflict(ascent, settings):
    settings.YOUTUBE_API_KEY = ''
    oil = MaintenanceItem.objects.get(key='oil')
    data = discover(ascent, oil)
    assert data['outcome'] == 'unavailable' and not data['videos']
    assert '2026' in data['search_url'] and 'Ascent' in data['search_url']
    assert '2.4L turbo flat-four' in queries(ascent, oil)[0][0]
    ascent.configuration = VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited')
    assert not candidate_matches({'snippet': {'title': '2021 Crosstrek Ascent 2.5L oil change'}}, ascent, oil)
