from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import httpx
import pytest
from django.core.management import call_command
from django.db import connection, close_old_connections
from django.urls import reverse
from django.utils import timezone

from garage.models import MaintenanceItem, VideoSearchCache, VehicleConfiguration
from garage.video_profiles import PROFILES
from garage.videos import (MATCH_LABEL, NOTICES, available, cache_key, candidate_matches,
                           discover, fetch_candidates, queries, reserve_search)


def response(data):
    r = MagicMock()
    r.json.return_value = data
    return r


def video(vid='one', title='2021 Subaru Crosstrek 2.5L oil and filter change', description=''):
    return {'id': vid, 'status': {'privacyStatus': 'public'},
            'snippet': {'title': title, 'description': description, 'channelTitle': 'Mechanic',
                        'thumbnails': {}, 'liveBroadcastContent': 'none'},
            'contentDetails': {'duration': 'PT10M'}}


def provider(*batches):
    client = MagicMock()
    responses = []
    for batch in batches:
        responses.append(response({'items': [{'id': {'videoId': v['id']}} for v in batch]}))
        if batch:
            responses.append(response({'items': batch}))
    client.get.side_effect = responses
    return client


def test_all_catalog_items_have_two_search_profiles(catalog):
    assert set(MaintenanceItem.objects.values_list('key', flat=True)) == set(PROFILES)
    assert all(len(p.phrases) == 2 and p.phrases[0] != p.phrases[1] for p in PROFILES.values())


def test_keyless_search_is_vehicle_specific(car, settings):
    settings.YOUTUBE_API_KEY = ''
    data = discover(car, MaintenanceItem.objects.get(key='oil'))
    assert not data['videos'] and '2021' in data['search_url'] and 'Crosstrek' in data['search_url']
    assert str(car.garage.pk) not in data['search_url']
    assert data['outcome'] == 'unavailable'


def test_queries_use_only_relevant_details(car):
    oil = MaintenanceItem.objects.get(key='oil')
    assert '2.5L' in queries(car, oil)[0][0]
    assert 'CVT' not in queries(car, oil)[0][0]
    assert '2.5L' not in queries(car, MaintenanceItem.objects.get(key='cabin'))[0][0]
    old = queries(car, oil)
    car.configuration.engine = 'New engine'
    assert queries(car, oil) != old


@pytest.mark.parametrize('title', [
    '2021 Subaru Crosstrek 2.5L oil and filter change',
    '2021 Crosstrek 2.5 oil change tutorial',
    '2018–2023 Crosstrek 2.5L oil change',
    'How to change engine oil on a 2021 Crosstrek 2.5L',
    'How to change the oil on a 2021 Subaru Crosstrek 2.5L BOXER engine',
])
def test_positive_service_and_vehicle_evidence(car, title):
    assert candidate_matches(video(title=title), car, MaintenanceItem.objects.get(key='oil'))


@pytest.mark.parametrize('title', [
    'Oil change', '2021 Subaru Crosstrek oil change',
    '2021 Subaru Forester 2.5L oil change', '2021 Toyota Corolla 2.5L oil change',
    '2021 Crosstrek Forester 2.5L oil change',
    '2021 Crosstrek 2.0L oil change', '2021 Crosstrek 2.5L V6 oil change',
    '2020 Subaru Crosstrek 2.5L oil change', '2018-2020 Crosstrek 2.5L oil change',
    '2018, 2023 Crosstrek 2.5L oil change',
    '2021 Crosstrek 2.5L manual transmission oil change',
    '2021 Crosstrek 2.5L FWD oil change', '2021 Crosstrek 2.5L engine oil review',
    '2021 Crosstrek 2.5L oil filter unboxing', '2021 Crosstrek 2.5L oil change buy now',
    '2021 Crosstrek 2.5L oil level inspection',
    '2021 Crosstrek 2.5L oil filter housing replacement',
    '2021 Crosstrek 2.5L oil pump replacement',
])
def test_irrelevant_candidates_rejected(car, title):
    assert not candidate_matches(video(title=title), car, MaintenanceItem.objects.get(key='oil'))


def test_description_requires_demonstration_not_keywords(car):
    item = MaintenanceItem.objects.get(key='oil')
    title = 'Engine oil and filter change'
    assert not candidate_matches(video(title=title, description='2021 Subaru Crosstrek 2.5L'), car, item)
    assert not candidate_matches(video(title=title, description='Tags: how to change engine oil 2021 Subaru Crosstrek 2.5L'), car, item)
    assert candidate_matches(video(title=title, description='In this video we change the engine oil on a 2021 Subaru Crosstrek 2.5L.'), car, item)
    assert not candidate_matches(video(title='2020 Crosstrek 2.5L oil change', description='In this video we change engine oil on a 2021 Crosstrek 2.5L.'), car, item)


@pytest.mark.parametrize('key,title,expected', [
    ('brakes', '2021 Crosstrek brake pad replacement', False),
    ('brakes', '2021 Crosstrek brake replacement check out the description', False),
    ('air-check', '2021 Crosstrek 2.5L air filter replacement check engine light', False),
    ('brakes', '2021 Crosstrek brake pad wear inspection', True),
    ('air', '2021 Crosstrek 2.5L cabin air filter replacement', False),
    ('air', '2021 Crosstrek 2.5L engine air filter replacement', True),
    ('air-check', '2021 Crosstrek 2.5L engine air filter replacement', False),
    ('air-check', '2021 Crosstrek 2.5L engine air filter inspection', True),
    ('cabin', '2021 Crosstrek cabin air filter replacement', True),
    ('cvt', '2021 Crosstrek 2.5L CVT fluid replacement', False),
    ('cvt', '2021 Crosstrek 2.5L CVT fluid level check', True),
    ('cvt-replace', '2021 Crosstrek 2.5L manual transmission oil replacement', False),
    ('cvt-replace', '2021 Crosstrek 2.5L CVT fluid drain and refill', True),
    ('diff-replace', '2021 Crosstrek AWD CVT front differential fluid change', False),
    ('diff-replace', '2021 Crosstrek AWD CVT front and rear differential fluid change', True),
])
def test_task_action_component_and_configuration(car, key, title, expected):
    assert candidate_matches(video(title=title), car, MaintenanceItem.objects.get(key=key)) is expected


def test_ford_front_rear_and_transmission(catalog):
    car = SimpleNamespace(configuration=VehicleConfiguration.objects.get(key='ford-f150-2010-4x4'))
    front = MaintenanceItem.objects.get(key='front-diff')
    assert candidate_matches(video(title='2010 Ford F-150 4x4 front differential fluid change'), car, front)
    assert not candidate_matches(video(title='2010 Ford F-150 4x4 rear differential fluid change'), car, front)
    at = MaintenanceItem.objects.get(key='at-fluid')
    assert candidate_matches(video(title='2010 F150 6R80 transmission fluid and filter change'), car, at)
    assert not candidate_matches(video(title='2010 F150 CVT transmission fluid change'), car, at)
    assert not candidate_matches(video(title='2010 F150 6R80 transmission fluid change'), car, at)
    assert not candidate_matches(video(title='2010 F150 Raptor 6R80 transmission fluid and filter change'), car, at)


def test_inspection_not_inferred_from_generic_advice(car):
    item = MaintenanceItem.objects.get(key='cabin-check')
    candidate = video(title='2021 Crosstrek cabin air filter replacement', description=(
        'This video shows how to replace the cabin air filter on a 2021 Crosstrek. '
        'Check your filter at every oil change.'))
    assert not candidate_matches(candidate, car, item)


def test_manual_coupe_rejects_sedan(catalog):
    car = SimpleNamespace(configuration=VehicleConfiguration.objects.get(key='nissan-altima-2012-manual-coupe'))
    assert not candidate_matches(video(title='2012 Altima sedan cabin air filter replacement'), car, MaintenanceItem.objects.get(key='cabin'))


def test_missing_profile_fails_closed(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    item = SimpleNamespace(key='unknown', action='inspect', search_phrase='unknown check')
    with patch('garage.videos.fetch_candidates') as lookup:
        assert discover(car, item)['outcome'] == 'no_matches'
        lookup.assert_not_called()


def test_lower_ranked_matches_deduplicated_and_cached(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    item = MaintenanceItem.objects.get(key='oil')
    client = provider([video('bad'+str(n), title='Oil change') for n in range(8)] + [video('one')], [video('one'), video('two')])
    with patch('garage.videos.httpx.Client') as cls:
        cls.return_value.__enter__.return_value = client
        result = discover(car, item)
        assert [v['id'] for v in result['videos']] == ['one', 'two']
        assert all(v['label'] == MATCH_LABEL for v in result['videos'])
        assert discover(car, item) == result
        assert client.get.call_count == 4
        for call in (client.get.call_args_list[0], client.get.call_args_list[2]):
            assert call.kwargs['params']['maxResults'] == 15
            assert '2021 Subaru Crosstrek' in call.kwargs['params']['q']
    cached = VideoSearchCache.objects.get()
    assert cached.expires_at - cached.fetched_at == timedelta(days=7)
    assert cached.lease_until is None


def test_stops_after_three(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    client = provider([video('three'), video('one'), video('two'), video('four')])
    with patch('garage.videos.httpx.Client') as cls:
        cls.return_value.__enter__.return_value = client
        result = discover(car, MaintenanceItem.objects.get(key='oil'))
    assert [v['id'] for v in result['videos']] == ['three', 'one', 'two']
    assert client.get.call_count == 2


def test_provider_ignores_missing_and_duplicate_ids_and_reorders_details(settings):
    settings.YOUTUBE_API_KEY = 'secret'
    client = MagicMock()
    client.get.side_effect = [response({'items': [{'id': {'videoId': x}} for x in ['two', 'gone', 'one', 'two']]}), response({'items': [video('one'), video('two')]})]
    assert [v['id'] for v in fetch_candidates(client, 'query')] == ['two', 'one']
    assert client.get.call_args.kwargs['params']['id'] == 'two,gone,one'


@pytest.mark.parametrize('field,value', [('private', True), ('live', 'live'), ('live', 'upcoming'), ('blocked', ['US']), ('allowed', ['CA'])])
def test_unavailable_videos_filtered(field, value):
    v = video()
    if field == 'private':
        v['status']['privacyStatus'] = 'private'
    elif field == 'live':
        v['snippet']['liveBroadcastContent'] = value
    else:
        v['contentDetails']['regionRestriction'] = {field: value}
    assert not available(v)


def test_empty_state_is_cached_with_notice(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    with patch('garage.videos.fetch_candidates', return_value=[]) as fetch:
        first = discover(car, MaintenanceItem.objects.get(key='oil'))
        assert first == discover(car, MaintenanceItem.objects.get(key='oil'))
        assert fetch.call_count == 2
    assert first['outcome'] == 'no_matches' and first['notice'] == NOTICES['no_matches']
    cache = VideoSearchCache.objects.get()
    assert cache.expires_at - cache.fetched_at == timedelta(days=1)


@pytest.mark.parametrize('partial', [False, True])
def test_provider_failure_preserves_partial_matches_and_cached_notice(car, settings, caplog, partial):
    settings.YOUTUBE_API_KEY = 'secret'
    with patch('garage.videos.fetch_candidates', side_effect=[[video()] if partial else [], httpx.TimeoutException('key=secret')]) as fetch:
        first = discover(car, MaintenanceItem.objects.get(key='oil'))
        assert discover(car, MaintenanceItem.objects.get(key='oil')) == first
        assert fetch.call_count == 2
    assert len(first['videos']) == int(partial)
    assert first['outcome'] == 'unavailable' and first['notice']
    assert 'secret' not in caplog.text
    cache = VideoSearchCache.objects.get()
    assert cache.expires_at - cache.fetched_at == timedelta(minutes=5)
    assert cache.lease_until is None


def test_quota_exhaustion_does_not_call_provider(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    settings.YOUTUBE_SEARCH_BUDGET = 0
    with patch('garage.videos.fetch_candidates') as fetch:
        assert discover(car, MaintenanceItem.objects.get(key='oil'))['outcome'] == 'unavailable'
        fetch.assert_not_called()


def test_pacific_quota_day(settings):
    from datetime import datetime, timezone as tz
    with patch('garage.videos.timezone.now', return_value=datetime(2026, 10, 12, 1, tzinfo=tz.utc)), patch('garage.videos.consume', return_value=True) as consume:
        assert reserve_search()
        assert consume.call_args.args[0] == 'youtube-search:2026-10-11'


def test_profile_version_invalidates_cache(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    item = MaintenanceItem.objects.get(key='oil')
    old = cache_key(car, item)
    VideoSearchCache.objects.create(key=old, results={'videos': [], 'outcome': 'no_matches'}, expires_at=timezone.now()+timedelta(days=1))
    with patch('garage.videos.PROFILE_VERSION', 999), patch('garage.videos.fetch_candidates', return_value=[]) as fetch:
        assert cache_key(car, item) != old
        discover(car, item)
        assert fetch.call_count == 2


def test_active_lease_avoids_provider_and_expired_lease_recovers(car, settings):
    settings.YOUTUBE_API_KEY = 'secret'
    item = MaintenanceItem.objects.get(key='oil')
    cached = VideoSearchCache.objects.create(key=cache_key(car, item), lease_until=timezone.now()+timedelta(seconds=90))
    with patch('garage.videos.fetch_candidates', return_value=[]) as fetch:
        assert discover(car, item)['outcome'] == 'refreshing'
        fetch.assert_not_called()
        cached.lease_until = timezone.now()-timedelta(seconds=1)
        cached.save()
        assert discover(car, item)['outcome'] == 'no_matches'
        assert fetch.call_count == 2


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_lookup_spends_quota_once(car, settings):
    if connection.vendor != 'postgresql':
        pytest.skip('Concurrent cache claims require PostgreSQL')
    settings.YOUTUBE_API_KEY = 'secret'
    item = MaintenanceItem.objects.get(key='oil')
    entered, release = Event(), Event()
    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return [video('one'), video('two'), video('three')]
    def run():
        close_old_connections()
        try:
            return discover(car, item)
        finally:
            connection.close()
    with patch('garage.videos.fetch_candidates', side_effect=fetch) as lookup, patch('garage.videos.reserve_search', return_value=True) as reserve, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        try:
            assert entered.wait(timeout=10)
            assert pool.submit(run).result(timeout=10)['outcome'] == 'refreshing'
        finally:
            release.set()
        assert first.result(timeout=10)['outcome'] == 'matches'
        assert lookup.call_count == reserve.call_count == 1


def test_cleanup_removes_old_metadata_not_garage(car):
    VideoSearchCache.objects.create(key='old', results={'videos': [], 'outcome': 'no_matches'}, fetched_at=timezone.now()-timedelta(days=31))
    call_command('cleanup')
    assert not VideoSearchCache.objects.exists()
    assert car.garage.vehicles.exists()


def test_throttled_video_panel_keeps_search_link(browser, car):
    item = MaintenanceItem.objects.get(key='oil')
    with patch('garage.views.consume', return_value=False), patch('garage.views.videos.discover') as lookup:
        result = browser.get(reverse('videos', args=[car.pk, item.pk]))
        assert result.status_code == 200 and b'Search YouTube' in result.content
        lookup.assert_not_called()


def test_video_endpoint_requires_owner_and_applicable_item(browser, car):
    from django.test import Client
    from conftest import account_client
    item = MaintenanceItem.objects.get(key='oil')
    url = reverse('videos', args=[car.pk, item.pk])
    from garage.models import Garage
    other, owner = account_client('not-owner')
    Garage.objects.create(owner=owner)
    with patch('garage.views.videos.discover') as lookup:
        assert Client().get(url).status_code == 302
        assert other.get(url).status_code == 404
        assert browser.get(reverse('videos', args=[car.pk, MaintenanceItem.objects.get(key='e85').pk])).status_code == 404
        lookup.assert_not_called()
