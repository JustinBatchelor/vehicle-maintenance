"""Restore the latest backup into an isolated, ephemeral PostgreSQL sidecar.

Does not connect to or modify the deployed application database. The backup PVC
is mounted read-only; restored data exists only in the verification pod's emptyDir.
"""
import json
import subprocess
from datetime import datetime,timezone

name='garage-restore-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
image='docker.io/library/postgres@sha256:3cec7eb015ba8adb28139fa5c83b8489cdf0e666e53dfdf20f598ae0cc8739e3'
security={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}
resources={'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'500m','memory':'512Mi'}}
env=[{'name':k,'value':v} for k,v in {'PGHOST':'127.0.0.1','PGUSER':'garage','PGPASSWORD':'restore-test-only','PGDATABASE':'restorecheck'}.items()]
script='''set -euo pipefail
dump=$(find /backups -maxdepth 1 -name 'garage-*.dump' | sort | tail -1)
test -n "$dump"
pg_restore --no-owner --no-acl --exit-on-error -d restorecheck "$dump"
test "$(psql -Atc 'SELECT count(*) FROM garage_vehicleconfiguration')" -ge 5
test "$(psql -Atc 'SELECT count(*) FROM garage_maintenancerule')" -gt 50
test "$(psql -Atc 'SELECT count(*) FROM django_migrations')" -gt 0
psql -c 'SELECT count(*) AS restored_configurations FROM garage_vehicleconfiguration'
psql -c 'SELECT count(*) AS restored_rules FROM garage_maintenancerule'
echo 'PASS: backup restored into isolated ephemeral PostgreSQL; production database untouched'
'''
job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name,'namespace':'vehicle-maintenance'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':300,'ttlSecondsAfterFinished':3600,'template':{'spec':{
 'restartPolicy':'Never','serviceAccountName':'garage','securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},
 'initContainers':[{'name':'restore-db','image':image,'restartPolicy':'Always','securityContext':security,'resources':resources,'env':[{'name':k,'value':v} for k,v in {'POSTGRES_USER':'garage','POSTGRES_PASSWORD':'restore-test-only','POSTGRES_DB':'restorecheck','PGDATA':'/restore/pgdata'}.items()], 'startupProbe':{'exec':{'command':['pg_isready','-h','127.0.0.1','-U','garage','-d','restorecheck']},'periodSeconds':2,'failureThreshold':60},'volumeMounts':[{'name':'restore-data','mountPath':'/restore'}]}],
 'containers':[{'name':'verify','image':image,'command':['/bin/bash','-c',script],'env':env,'securityContext':security,'resources':resources,'volumeMounts':[{'name':'backups','mountPath':'/backups','readOnly':True}]}],
 'volumes':[{'name':'restore-data','emptyDir':{'sizeLimit':'2Gi'}},{'name':'backups','persistentVolumeClaim':{'claimName':'garage-backups','readOnly':True}}]
 }}}}
subprocess.run(['oc','create','-f','-'],input=json.dumps(job),text=True,check=True)
result=subprocess.run(['oc','-n','vehicle-maintenance','wait','job/'+name,'--for=condition=complete','--timeout=240s'])
subprocess.run(['oc','-n','vehicle-maintenance','logs','job/'+name,'-c','verify'],check=True)
if result.returncode:raise SystemExit(result.returncode)
