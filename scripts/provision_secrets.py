"""Create fresh deployment secrets if absent; never print secret values."""
import json
import secrets
import subprocess
import sys

namespace='vehicle-maintenance'
def run(*args,**kwargs):return subprocess.run(['oc','-n',namespace,*args],check=True,**kwargs)
def exists(name):
    return subprocess.run(['oc','-n',namespace,'get','secret',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
if exists('garage-app') and exists('garage-db'):
    print('Existing secrets retained');sys.exit(0)
if exists('garage-app') or exists('garage-db'):
    raise SystemExit('Only one deployment secret exists. Reconcile credentials manually; refusing to overwrite.')
password=secrets.token_urlsafe(36)
for name,values in [('garage-db',{'password':password}),('garage-app',{'DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'DATABASE_URL':f'postgresql://garage:{password}@garage-db:5432/garage'})]:
    resource={'apiVersion':'v1','kind':'Secret','metadata':{'name':name},'type':'Opaque','stringData':values}
    run('create','-f','-',input=json.dumps(resource),text=True,stdout=subprocess.DEVNULL)
print('Created application and database secrets; values were not logged')
