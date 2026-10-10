from datetime import timedelta
from unittest.mock import patch,MagicMock
import httpx
from django.utils import timezone
from django.core.management import call_command
from garage.models import MaintenanceItem,VideoSearchCache
from garage.videos import discover,queries

def test_keyless_search_is_vehicle_specific(car,settings):
    settings.YOUTUBE_API_KEY=''
    data=discover(car,MaintenanceItem.objects.get(key='oil'))
    assert not data['videos'] and '2021' in data['search_url'] and 'Crosstrek' in data['search_url']
    assert str(car.garage.pk) not in data['search_url']

def test_queries_follow_changed_config(car):
    item=MaintenanceItem.objects.get(key='oil')
    old=queries(car,item)
    car.configuration.engine='New engine'
    assert queries(car,item)!=old

def response(data):
    r=MagicMock();r.json.return_value=data;return r

def video(vid):
    return {'id':vid,'status':{'privacyStatus':'public'},'snippet':{'title':'Oil change','channelTitle':'Mechanic','thumbnails':{},'liveBroadcastContent':'none'},'contentDetails':{'duration':'PT10M'}}

def test_broader_results_deduplicated_and_cached(car,settings):
    settings.YOUTUBE_API_KEY='secret';item=MaintenanceItem.objects.get(key='oil')
    client=MagicMock()
    client.get.side_effect=[response({'items':[{'id':{'videoId':'one'}}]}),response({'items':[video('one')]}),response({'items':[{'id':{'videoId':'one'}},{'id':{'videoId':'two'}}]}),response({'items':[video('one'),video('two')]}),response({'items':[]})]
    with patch('garage.videos.httpx.Client') as cls:
        cls.return_value.__enter__.return_value=client
        result=discover(car,item)
        assert [v['id'] for v in result['videos']]==['one','two']
        assert result['videos'][1]['label']=='Broader model search'
        assert discover(car,item)['videos']==result['videos']
        assert client.get.call_count==5

def test_api_failure_and_quota_fallback(car,settings):
    settings.YOUTUBE_API_KEY='secret';settings.YOUTUBE_SEARCH_BUDGET=0
    with patch('garage.videos.httpx.Client') as cls:
        result=discover(car,MaintenanceItem.objects.get(key='oil'))
        assert not result['videos'] and result['search_url']
        cls.return_value.__enter__.return_value.get.assert_not_called()
    settings.YOUTUBE_SEARCH_BUDGET=80
    with patch('garage.videos.httpx.Client') as cls:
        cls.return_value.__enter__.return_value.get.side_effect=httpx.TimeoutException('timeout')
        assert not discover(car,MaintenanceItem.objects.get(key='tires'))['videos']

def test_removed_private_video_omitted(car,settings):
    settings.YOUTUBE_API_KEY='secret';settings.YOUTUBE_SEARCH_BUDGET=1
    v=video('private');v['status']['privacyStatus']='private'
    client=MagicMock();client.get.side_effect=[response({'items':[{'id':{'videoId':'private'}},{'id':{'videoId':'deleted'}}]}),response({'items':[v]})]
    with patch('garage.videos.httpx.Client') as cls:
        cls.return_value.__enter__.return_value=client
        assert discover(car,MaintenanceItem.objects.get(key='oil'))['videos']==[]

def test_cleanup_removes_old_metadata_not_garage(car):
    VideoSearchCache.objects.create(key='old',results=[{'title':'old'}],fetched_at=timezone.now()-timedelta(days=31))
    call_command('cleanup');assert not VideoSearchCache.objects.exists()
    assert car.garage.vehicles.exists()

def test_throttled_video_panel_keeps_search_link(browser,car):
    from django.urls import reverse
    item=MaintenanceItem.objects.get(key='oil')
    with patch('garage.views.consume',return_value=False),patch('garage.views.videos.discover') as lookup:
        result=browser.get(reverse('videos',args=[car.pk,item.pk]))
        assert result.status_code==200 and b'Search YouTube' in result.content
        lookup.assert_not_called()
