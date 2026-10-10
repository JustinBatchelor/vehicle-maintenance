import json
import time
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from garage.models import VehicleConfiguration
class Command(BaseCommand):
    help="Wait for release migrations and the image's reviewed catalog to be imported."
    def handle(self,*args,**kwargs):
        catalog=json.loads((settings.BASE_DIR/'data/schedules.json').read_text())
        versions={s['key']:s['version'] for s in catalog['schedules']}
        for _ in range(120):
            try:
                executor=MigrationExecutor(connection)
                pending=executor.migration_plan(executor.loader.graph.leaf_nodes())
                ready=all(VehicleConfiguration.objects.filter(key=c['key'],schedule__version=versions[c['schedule']],schedule__reviewed=True).exists() for c in catalog['configurations'])
                if not pending and ready:return
            except Exception:connection.close()
            time.sleep(5)
        raise CommandError("Release migrations/catalog were not ready within ten minutes")
