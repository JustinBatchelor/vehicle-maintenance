"""Authorized release check: restart application/database pods with a test record.

Touches only the created acceptance vehicle; does not print session credentials.
"""
import os
import subprocess
import time
from playwright.sync_api import sync_playwright,expect

base='https://garage.apps.sno.batchelor.live'
def oc(*args):subprocess.run(['oc','-n','vehicle-maintenance',*args],check=True)
def visit_after_restart(page,url):
    # Router endpoint propagation may briefly outlast workload readiness.
    for _ in range(30):
        response=page.goto(url)
        if response.status < 500:break
        time.sleep(1)
    expect(page.get_by_role('heading',name='Persistence acceptance',exact=True)).to_be_visible()
with sync_playwright() as p:
    assert os.getenv('GARAGE_STORAGE_STATE'), 'Supply a dedicated Google test account browser storage state'
    browser=p.chromium.launch();context=browser.new_context(storage_state=os.environ['GARAGE_STORAGE_STATE']);page=context.new_page()
    page.goto(base+'/vehicles/new/')
    page.locator('#select-make').select_option('Subaru')
    page.locator('#id_nickname').fill('Persistence acceptance')
    page.locator('#id_initial_miles').fill('50000');page.locator('#id_reading_date').fill('2026-10-01')
    page.get_by_role('button',name='Save vehicle').click();url=page.url
    oil=page.locator('.task').filter(has=page.get_by_role('heading',name='Engine oil and filter',exact=True))
    oil.get_by_role('link',name='Log service',exact=True).click()
    page.locator('#id_date').fill('2026-07-01');page.locator('#id_miles').fill('45000')
    page.get_by_role('button',name='Save',exact=True).click()
    oc('rollout','restart','deployment/garage-web')
    oc('rollout','status','deployment/garage-web','--timeout=120s')
    visit_after_restart(page,url)
    expect(page.locator('#history + .table-wrap')).to_contain_text('45000')
    oc('delete','pod','garage-db-0','--wait=true')
    oc('wait','pod/garage-db-0','--for=condition=Ready','--timeout=120s')
    visit_after_restart(page,url)
    expect(page.locator('#history + .table-wrap')).to_contain_text('45000')
    page.goto(url+'delete/');page.get_by_role('button',name='Delete',exact=True).click()
    page.goto(base+'/settings/');page.get_by_role('button',name='Sign out').click()
    browser.close()
print('PASS: browser garage and completed service survived web/database pod restarts')
