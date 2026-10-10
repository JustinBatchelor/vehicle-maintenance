"""Run desktop/mobile browser acceptance against a disposable garage.

Usage: GARAGE_URL=http://127.0.0.1:8018 python scripts/browser_check.py
Requires GARAGE_STORAGE_STATE for a dedicated Google test account on live sites.
For loopback-only development, set GARAGE_LOCAL_TEST_ACCOUNT=1 to create a disposable
local Google-identity fixture. This never creates a production login endpoint.
"""
import os
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from playwright.sync_api import sync_playwright,expect

base=os.getenv("GARAGE_URL","http://127.0.0.1:8018").rstrip('/')
out=Path(os.getenv("BROWSER_ARTIFACTS","/private/tmp/garage-browser-check"));out.mkdir(parents=True,exist_ok=True)
local_user = None
state = os.getenv('GARAGE_STORAGE_STATE')
if os.getenv('GARAGE_LOCAL_TEST_ACCOUNT') == '1':
    assert urlparse(base).hostname in ('127.0.0.1','localhost'), 'Local fixtures are restricted to loopback'
    import sys, uuid
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.test import Client
    from allauth.socialaccount.models import SocialAccount
    from garage.models import Garage
    label='browser-'+uuid.uuid4().hex
    local_user=get_user_model().objects.create_user(username=label,email=label+'@example.com')
    SocialAccount.objects.create(user=local_user,provider='google',uid=label)
    Garage.objects.create(owner=local_user)
    def local_cookie():
        client=Client();client.force_login(local_user,backend='allauth.account.auth_backends.AuthenticationBackend')
        return {'name':'sessionid','value':client.cookies['sessionid'].value,'url':base,'httpOnly':True,'sameSite':'Lax'}
    local_cookies=[local_cookie(),local_cookie()]
else:
    assert state, 'Supply GARAGE_STORAGE_STATE for a dedicated Google test account; no live authentication bypass exists'
with sync_playwright() as p:
    browser=p.chromium.launch()
    context=browser.new_context(viewport={"width":1440,"height":1000},storage_state=state)
    if local_user:context.add_cookies([local_cookies[0]])
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(base);page.screenshot(path=str(out/'welcome-desktop.png'),full_page=True)
    page.goto(base+'/vehicles/new/')
    urls=[]
    for make,label,mileage in [('Subaru',None,50000),('Ford','5.4L V8 · 6R80 automatic · 4x4',140000),('Nissan','3.5L V6 · CVT · FWD',90000)]:
        if urls:page.goto(base+'/vehicles/new/')
        page.locator('#select-make').select_option(make)
        if label:page.locator('#id_configuration').select_option(label=label)
        page.locator('#id_nickname').fill('Browser acceptance '+make)
        page.locator('#id_in_service_date').fill('2021-01-01' if make=='Subaru' else '2012-01-01' if make=='Nissan' else '2010-01-01')
        page.locator('#id_initial_miles').fill(str(mileage))
        page.locator('#id_reading_date').fill('2026-10-01')
        expect(page.locator('#id_assume_maintained')).to_be_checked()
        page.get_by_role('button',name='Save vehicle').click()
        expect(page.get_by_role('heading',name='Browser acceptance '+make,exact=True)).to_be_visible()
        assert page.locator('.task').count()>10
        expect(page.get_by_role('heading',name='Starting with maintenance up to date')).to_be_visible()
        page.locator('#status-filter').select_option('upcoming')
        assert page.locator('.task:visible').count()>0
        page.locator('#status-filter').select_option('all')
        urls.append(page.url)
    page.goto(base);expect(page.locator('.vehicle-card')).to_have_count(3)
    page.screenshot(path=str(out/'garage-desktop.png'),full_page=True)
    page.goto(urls[0])
    oil=page.locator('.task').filter(has=page.get_by_role('heading',name='Engine oil and filter',exact=True))
    oil.get_by_text('How-to videos',exact=False).click()
    expect(oil.get_by_role('link',name='Search YouTube for this task')).to_be_visible()
    assert 'Crosstrek' in oil.get_by_role('link',name='Search YouTube for this task').get_attribute('href')
    oil.get_by_role('link',name='Log service',exact=True).click()
    page.locator('#id_date').fill('2026-07-01');page.locator('#id_miles').fill('45000');page.locator('#id_cost').fill('49.95');page.locator('#id_notes').fill('Browser test only')
    page.get_by_role('button',name='Save',exact=True).click()
    oil=page.locator('.task').filter(has=page.get_by_role('heading',name='Engine oil and filter',exact=True))
    expect(oil.get_by_text('51000 miles',exact=False)).to_be_visible()
    oil.get_by_role('link',name='Plan',exact=True).click()
    page.locator('#id_title').fill('Oil and filter service');page.locator('#id_date').fill('2026-12-31');page.locator('#id_notes').fill('Private appointment note')
    page.get_by_role('button',name='Save',exact=True).click()
    expect(page.get_by_role('heading',name='Oil and filter service',exact=True)).to_be_visible()
    google=page.get_by_role('link',name='Add to Google Calendar').get_attribute('href')
    query=parse_qs(urlparse(google).query);assert query['dates']==['20261231/20270101'];assert 'Private appointment note' not in query['details'][0]
    with page.expect_download() as download:page.get_by_role('link',name='Download .ics').click()
    data=Path(download.value.path()).read_text();assert '20261231' in data and '20270101' in data
    page.screenshot(path=str(out/'appointment-desktop.png'),full_page=True)
    # A second anonymous browser is denied; the same Google owner sees the garage.
    second=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    mobile=second.new_page();mobile.goto(urls[0]);assert mobile.url==base+'/accounts/login/'
    if local_user:second.add_cookies([local_cookies[1]])
    else:second.add_cookies(context.cookies())
    mobile.goto(base)
    expect(mobile.locator('.vehicle-card')).to_have_count(3)
    mobile.screenshot(path=str(out/'garage-mobile.png'),full_page=True)
    assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    mobile.goto(urls[0]);mobile.locator('#status-filter').select_option('upcoming')
    assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    mobile.screenshot(path=str(out/'vehicle-mobile.png'),full_page=True)
    for url in urls:
        page.goto(url+'delete/');page.get_by_role('button',name='Delete',exact=True).click()
    page.goto(base+'/settings/');page.get_by_role('button',name='Sign out').click()
    assert not errors,errors
    browser.close()
if local_user:
    Garage.objects.filter(owner=local_user).delete();local_user.delete()
print('PASS: three vehicles, desktop/mobile, service log, videos, calendar, account sessions, isolation, cleanup')
