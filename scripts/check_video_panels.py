"""Local-only Playwright check of real HTMX panels using synthetic provider data.

Uses a temporary database, a loopback HTTP server, and an ordinary authenticated
session. Makes no Google/YouTube requests and never changes deployment settings.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from socketserver import ThreadingMixIn
import os
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with TemporaryDirectory(prefix='garage-video-browser-') as temporary:
        os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DATABASE_URL='sqlite:///'+temporary+'/test.sqlite3',
                          DEBUG='true', COOKIE_SECURE='false', ALLOWED_HOSTS='localhost,127.0.0.1,testserver', YOUTUBE_API_KEY='synthetic-test-key')
        import django
        django.setup()
        import httpx
        from django.core.management import call_command
        from django.contrib.auth import get_user_model
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.servers.basehttp import WSGIServer, WSGIRequestHandler
        from django.core.wsgi import get_wsgi_application
        from django.test import Client
        from garage.models import Garage, Vehicle, VehicleConfiguration, OdometerReading, VideoSearchCache
        from allauth.socialaccount.models import SocialAccount
        from playwright.sync_api import sync_playwright, expect
        call_command('migrate', verbosity=0)
        call_command('import_schedules', verbosity=0)
        user = get_user_model().objects.create_user(username='video-browser')
        SocialAccount.objects.create(user=user, provider='google', uid='video-browser')
        garage = Garage.objects.create(owner=user)
        car = Vehicle.objects.create(garage=garage, configuration=VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited'))
        OdometerReading.objects.create(vehicle=car, miles=50000)
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
        out = Path(os.environ.get('BROWSER_ARTIFACTS', '/private/tmp/garage-video-panels'))
        out.mkdir(parents=True, exist_ok=True)
        entered, release = Event(), Event()
        state = {'outcome': 'matches'}
        def fetch(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=15):
                raise httpx.TimeoutException('Synthetic delay')
            if state['outcome'] == 'unavailable':
                raise httpx.TimeoutException('Synthetic outage')
            if state['outcome'] == 'no_matches':
                return []
            return [{'id': 'synthetic-'+str(n), 'status': {'privacyStatus': 'public'},
                     'snippet': {'title': '2021 Subaru Crosstrek 2.5L oil and filter change tutorial '+str(n),
                                 'channelTitle': 'Synthetic Test Channel', 'liveBroadcastContent': 'none'},
                     'contentDetails': {'duration': 'PT12M'}} for n in range(3)]
        errors = []
        try:
            with patch('garage.videos.fetch_candidates', side_effect=fetch), patch('garage.videos.reserve_search', return_value=True), ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as p:
                browser = p.chromium.launch()
                for width in [1440, 390]:
                    context = browser.new_context(viewport={'width': width, 'height': 1000})
                    context.add_cookies([{'name': 'sessionid', 'value': client.cookies['sessionid'].value, 'url': base}])
                    page = context.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    for outcome in ['matches', 'no_matches', 'unavailable']:
                        db.submit(lambda: VideoSearchCache.objects.all().delete()).result()
                        state['outcome'] = outcome
                        entered.clear()
                        release.clear()
                        page.goto(base+f'/vehicles/{car.pk}/')
                        task = page.locator('.task').filter(has=page.get_by_role('heading', name='Engine oil and filter', exact=True))
                        task.get_by_text('How-to videos', exact=False).click()
                        assert entered.wait(timeout=10)
                        expect(task.get_by_text('Loading tutorial options…')).to_be_visible()
                        if outcome == 'matches':
                            task.screenshot(path=str(out/f'{width}-loading.png'))
                        release.set()
                        panel = task.locator('.video-results')
                        expect(panel).to_have_attribute('data-outcome', outcome)
                        expect(panel.get_by_role('link', name='Search YouTube for this task')).to_be_visible()
                        expect(panel.locator('.video-card')).to_have_count(3 if outcome == 'matches' else 0)
                        if outcome == 'no_matches':
                            expect(panel.get_by_text('No close video matches found for this vehicle and service.')).to_be_visible()
                        if outcome == 'unavailable':
                            expect(panel.get_by_text('Video search is unavailable right now. You can still search YouTube.')).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                        task.screenshot(path=str(out/f'{width}-{outcome}.png'))
                    context.close()
                browser.close()
            assert not errors, errors
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        print('PASS: real HTMX loading, matched, empty and unavailable panels at 1440px and 390px; synthetic provider only')


if __name__ == '__main__':
    main()
