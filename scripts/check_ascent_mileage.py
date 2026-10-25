"""Ascent setup and inline mileage acceptance against a disposable local garage."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from socketserver import ThreadingMixIn
from tempfile import TemporaryDirectory
from threading import Thread
import os
import re
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with TemporaryDirectory(prefix='garage-ascent-') as temporary:
        os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DATABASE_URL='sqlite:///'+temporary+'/test.sqlite3',
                          DEBUG='true', COOKIE_SECURE='false', ALLOWED_HOSTS='localhost,127.0.0.1,testserver', YOUTUBE_API_KEY='')
        import django
        django.setup()
        from django.core.management import call_command
        from django.contrib.auth import get_user_model
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.servers.basehttp import WSGIServer, WSGIRequestHandler
        from django.core.wsgi import get_wsgi_application
        from django.test import Client
        from django.utils import timezone
        from allauth.socialaccount.models import SocialAccount
        from garage.models import Garage, Vehicle
        from playwright.sync_api import sync_playwright, expect

        call_command('migrate', verbosity=0)
        call_command('import_schedules', verbosity=0)
        user = get_user_model().objects.create_user(username='ascent-browser')
        SocialAccount.objects.create(user=user, provider='google', uid='ascent-browser')
        garage = Garage.objects.create(owner=user)
        client = Client()
        client.force_login(user, backend='allauth.account.auth_backends.AuthenticationBackend')

        class Server(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args):
                pass

        server = Server(('127.0.0.1', 0), QuietHandler)
        server.set_app(StaticFilesHandler(get_wsgi_application()))
        base = f'http://127.0.0.1:{server.server_port}'
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        out = Path(os.environ.get('BROWSER_ARTIFACTS', '/private/tmp/garage-ascent-browser'))
        out.mkdir(parents=True, exist_ok=True)
        errors = []
        cookie = {'name': 'sessionid', 'value': client.cookies['sessionid'].value, 'url': base}

        def assert_saved(nickname, miles, count):
            car = Vehicle.objects.get(garage=garage, nickname=nickname)
            assert car.configuration.key == 'subaru-ascent-2026-limited'
            assert car.latest_reading.miles == miles and car.readings.count() == count
            assert car.assumed_through_miles == 120 and not car.records.exists()

        try:
            with ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as p:
                browser = p.chromium.launch()
                for width in [1440, 390]:
                    nickname = f'Ascent browser {width}'
                    context = browser.new_context(viewport={'width': width, 'height': 1000})
                    context.add_cookies([cookie])
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base+'/vehicles/new/')
                    page.locator('#select-make').select_option('Subaru')
                    page.locator('#select-model').select_option('Ascent')
                    expect(page.locator('#select-year')).to_have_value('2026')
                    expect(page.locator('#select-trim')).to_have_value('Limited')
                    expect(page.locator('#id_configuration option:checked')).to_contain_text('2.4L turbo flat-four')
                    expect(page.locator('#id_conditions input')).to_have_count(0)
                    page.locator('#id_nickname').fill(nickname)
                    page.locator('#id_initial_miles').fill('120')
                    page.locator('#id_in_service_date').fill(timezone.localdate().isoformat())
                    page.locator('#id_reading_date').fill(timezone.localdate().isoformat())
                    page.get_by_role('button', name='Save vehicle', exact=True).click()
                    expect(page.get_by_role('heading', name='Maintenance timeline', exact=True)).to_be_visible()
                    detail = page.url
                    field = page.get_by_label('Current odometer (miles)')
                    expect(field).to_have_value('120')
                    oil = page.locator('.timeline-item').filter(has=page.get_by_role('heading', name='Engine oil and filter', exact=True))
                    expect(oil.locator('.status')).to_have_text('Upcoming')
                    field.fill('5500')
                    field.press('Enter')
                    expect(page.get_by_text('Mileage updated. Maintenance status has been recalculated.', exact=True)).to_be_visible()
                    expect(page.locator('.mileage-observation strong')).to_have_text('5500')
                    expect(oil.locator('.status')).to_have_text('Due soon')
                    expect(oil.locator('.timeline-limits')).to_contain_text('6000 miles')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    page.screenshot(path=str(out/f'{width}-timeline-top.png'))
                    page.get_by_role('link', name='Detailed list', exact=True).click()
                    field.fill('6001')
                    page.get_by_role('button', name='Save mileage', exact=True).click()
                    expect(page.get_by_role('link', name='Detailed list', exact=True)).to_have_attribute('aria-current', 'page')
                    expect(page.locator('.mileage-observation strong')).to_have_text('6001')
                    task = page.locator('.task').filter(has=page.get_by_role('heading', name='Engine oil and filter', exact=True))
                    expect(task.locator('.status')).to_have_text('Overdue')
                    field.fill('5999')
                    page.get_by_role('button', name='Save mileage', exact=True).click()
                    expect(page.locator('.quick-mileage .errorlist')).to_contain_text('Mileage cannot be lower')
                    expect(field).to_have_value('5999')
                    expect(page.locator('.mileage-observation strong')).to_have_text('6001')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    page.screenshot(path=str(out/f'{width}-inline-error.png'))
                    field.fill('6001')
                    page.get_by_role('button', name='Save mileage', exact=True).click()
                    expect(page.get_by_text('This mileage is already recorded for today. Maintenance status is up to date.', exact=True)).to_be_visible()
                    db.submit(assert_saved, nickname, 6001, 3).result()
                    expect(page.get_by_role('link', name='Other date or engine hours')).to_be_visible()
                    expect(page.get_by_role('link', name='Correct reading', exact=True)).to_be_visible()
                    task.get_by_text('How-to videos', exact=False).click()
                    expect(task.get_by_role('link', name='Search YouTube for this task')).to_have_attribute('href', re.compile('.*2026.*Ascent.*'))
                    context.close()

                context = browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 844})
                context.add_cookies([cookie])
                page = context.new_page()
                page.goto(detail+'?view=list')
                page.get_by_label('Current odometer (miles)').fill('6002')
                page.get_by_role('button', name='Save mileage', exact=True).click()
                expect(page.locator('.mileage-observation strong')).to_have_text('6002')
                expect(page.get_by_role('link', name='Detailed list', exact=True)).to_have_attribute('aria-current', 'page')
                db.submit(assert_saved, 'Ascent browser 390', 6002, 4).result()
                db.submit(assert_saved, 'Ascent browser 1440', 6001, 3).result()
                page.screenshot(path=str(out/'390-no-js.png'))
                browser.close()
            assert not errors, errors
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        print('PASS: Ascent setup, inline mileage, recalculation, validation, duplicate save, both views, keyboard, mobile, no-JS, vehicle isolation, video fallback')


if __name__ == '__main__':
    main()
