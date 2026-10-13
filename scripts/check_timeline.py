"""Local timeline acceptance: temporary database, real HTMX, no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from socketserver import ThreadingMixIn
from tempfile import TemporaryDirectory
from threading import Thread
import os
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with TemporaryDirectory(prefix='garage-timeline-') as temporary:
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
        from garage.models import Garage, Vehicle, VehicleConfiguration, OdometerReading, ServiceRecord
        from playwright.sync_api import sync_playwright, expect

        call_command('migrate', verbosity=0)
        call_command('import_schedules', verbosity=0)
        user = get_user_model().objects.create_user(username='timeline-browser')
        SocialAccount.objects.create(user=user, provider='google', uid='timeline-browser')
        garage = Garage.objects.create(owner=user)
        car = Vehicle.objects.create(garage=garage, configuration=VehicleConfiguration.objects.get(key='subaru-crosstrek-2021-limited'),
                                     assumed_through_miles=50000, assumed_through_date=timezone.localdate())
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
        out = Path(os.environ.get('BROWSER_ARTIFACTS', '/private/tmp/garage-timeline-browser'))
        out.mkdir(parents=True, exist_ok=True)
        errors = []
        cookie = {'name': 'sessionid', 'value': client.cookies['sessionid'].value, 'url': base}
        url = base+f'/vehicles/{car.pk}/'
        try:
            with ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as p:
                browser = p.chromium.launch()
                for width in [1440, 390]:
                    context = browser.new_context(viewport={'width': width, 'height': 1000})
                    context.add_cookies([cookie])
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(url)
                    expect(page.get_by_role('heading', name='Maintenance timeline', exact=True)).to_be_visible()
                    expect(page.get_by_role('button', name='Complete selected', exact=True)).to_be_disabled()
                    assert page.locator('input[name="items"]:checked').count() == 0
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    milestones = page.locator('.timeline-milestone').evaluate_all('(nodes) => nodes.map(n => Number(n.dataset.miles))')
                    assert milestones == sorted(milestones)
                    page.screenshot(path=str(out/f'{width}-timeline.png'), full_page=True)
                    page.screenshot(path=str(out/f'{width}-timeline-top.png'))
                    oil = page.locator('.timeline-item').filter(has=page.get_by_role('heading', name='Engine oil and filter', exact=True))
                    tires = page.locator('.timeline-item').filter(has=page.get_by_role('heading', name='Tire rotation and wear check', exact=True))
                    oil.get_by_role('checkbox').focus()
                    page.keyboard.press('Space')
                    tires.get_by_role('checkbox').check()
                    expect(page.locator('#selection-count')).to_have_text('2 services selected')
                    page.get_by_role('button', name='Complete selected', exact=True).click()
                    expect(page.get_by_role('heading', name='Confirm completed service')).to_be_focused()
                    expect(page.locator('#completion-panel > ul > li')).to_have_count(2)
                    expect(page.locator('#id_miles')).to_have_value('50000' if width == 1440 else '50500')
                    # Chronological conflict, not HTML number validation.
                    page.get_by_text('More options', exact=True).click()
                    page.locator('#id_date').fill('2026-01-01')
                    page.locator('#id_miles').fill('80000')
                    page.get_by_role('button', name='Save completed service', exact=True).click()
                    expect(page.get_by_text('Mileage conflicts with earlier or later records. Correct the conflicting reading first.')).to_be_visible()
                    expect(page.locator('#id_miles')).to_have_value('80000')
                    expect(page.locator('#completion-panel > ul > li')).to_have_count(2)
                    page.locator('#id_date').fill(timezone.localdate().isoformat())
                    expect(page.locator('[data-completion-date]')).to_have_text(timezone.localdate().isoformat())
                    page.locator('#id_miles').fill('50500')
                    page.screenshot(path=str(out/f'{width}-confirmation.png'), full_page=True)
                    page.locator('#completion-panel').screenshot(path=str(out/f'{width}-confirmation-panel.png'))
                    before = db.submit(lambda: ServiceRecord.objects.filter(vehicle=car).count()).result()
                    page.get_by_role('button', name='Save completed service', exact=True).click()
                    expect(page.get_by_text('2 services recorded. Due dates have been recalculated.')).to_be_visible()
                    expect(page.locator('.mileage-strip strong')).to_have_text('50500')
                    assert db.submit(lambda: ServiceRecord.objects.filter(vehicle=car).count()).result() == before+2
                    expect(oil.locator('.timeline-limits')).to_contain_text('56500 miles')
                    expect(page.locator('input[name="items"]:checked')).to_have_count(0)
                    # Single-item completion and cancel leave no records.
                    oil.get_by_role('link', name='Complete', exact=True).click()
                    expect(page.locator('#completion-panel > ul > li')).to_have_count(1)
                    page.get_by_role('link', name='Cancel', exact=True).click()
                    expect(page.locator('#completion-heading')).to_have_count(0)
                    # Existing links stay usable inside expandable details.
                    oil.get_by_text('Service details, history & tutorials', exact=True).click()
                    oil.get_by_text('How-to videos', exact=False).click()
                    expect(oil.get_by_role('link', name='Search YouTube for this task')).to_be_visible()
                    page.get_by_role('link', name='Detailed list', exact=True).click()
                    page.locator('#status-filter').select_option('upcoming')
                    assert page.locator('.task:visible').count() > 0
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    context.close()
                context = browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 844})
                context.add_cookies([cookie])
                page = context.new_page()
                page.goto(url)
                page.locator('input[form="completion-selection"]').first.check()
                page.get_by_role('button', name='Complete selected', exact=True).click()
                expect(page.get_by_role('heading', name='Confirm completed service')).to_be_visible()
                expect(page.locator('#completion-panel > ul > li')).to_have_count(1)
                page.get_by_role('button', name='Save completed service', exact=True).click()
                expect(page.get_by_text('1 service recorded. Due dates have been recalculated.')).to_be_visible()
                browser.close()
            assert not errors, errors
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        print('PASS: timeline, keyboard selection, batch/single confirmation, errors, history/mileage refresh, mobile, detailed list, tutorials, no-JS save')


if __name__ == '__main__':
    main()
