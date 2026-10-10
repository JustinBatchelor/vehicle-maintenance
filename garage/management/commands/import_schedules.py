import json
import re
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from garage.models import SourceDocument, MaintenanceItem, ScheduleVersion, MaintenanceRule, VehicleConfiguration

class Command(BaseCommand):
    help = "Validate and atomically import reviewed manufacturer schedules. Same version must be immutable."
    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(settings.BASE_DIR / "data/schedules.json"))
    @transaction.atomic
    def handle(self,*args,**options):
        try:
            data = json.loads(Path(options["path"]).read_text())
            if data["schema_version"] != 1: raise ValueError("Unsupported schema version")
            sources, items, schedules = {}, {}, {}
            for raw in data["sources"]:
                if not re.fullmatch(r"[a-f0-9]{64}", raw["sha256"]): raise ValueError("Invalid document checksum")
                obj=SourceDocument(**raw);obj.full_clean(validate_unique=False)
                sources[raw["key"]],_=SourceDocument.objects.update_or_create(key=raw["key"],defaults=raw)
            for raw in data["items"]:
                obj=MaintenanceItem(**raw);obj.full_clean(validate_unique=False)
                items[raw["key"]],_=MaintenanceItem.objects.update_or_create(key=raw["key"],defaults=raw)
            for raw in data["schedules"]:
                values = {k:v for k,v in raw.items() if k not in ["source","rules"]}
                if not raw["reviewed"] or not raw["reviewed_on"]: raise ValueError("Schedules must be reviewed before activation")
                # Versions use distinct records; historical rules remain available for records.
                version_key=raw["key"]+"-"+raw["version"].replace(".","-")
                values["key"]=version_key
                values["source"]=sources[raw["source"]]
                schedule,_=ScheduleVersion.objects.update_or_create(key=version_key,defaults=values)
                schedules[raw["key"]]=schedule
                keys=set()
                for r in raw["rules"]:
                    if r["key"] in keys: raise ValueError("Duplicate rule key")
                    keys.add(r["key"])
                    if r.get("basis","milestone") != "conditional" and not (r.get("miles") or r.get("months")): raise ValueError("Timed rule requires a positive interval")
                    for field in ["miles","months","hours","first_miles","first_months"]:
                        if r.get(field) is not None and r[field] <= 0: raise ValueError("Intervals must be positive")
                    values={k:v for k,v in r.items() if k!="item"}
                    values.update(schedule=schedule,item=items[r["item"]])
                    obj=MaintenanceRule(**values);obj.full_clean(validate_unique=False,validate_constraints=False)
                    prior=MaintenanceRule.objects.filter(schedule=schedule,key=r["key"]).first()
                    if prior:
                        for field in obj._meta.fields:
                            if field.name != "id" and getattr(prior,field.attname)!=getattr(obj,field.attname): raise ValueError("Change the dataset version before changing a published rule")
                    else: obj.save()
                if schedule.rules.exclude(key__in=keys).exists(): raise ValueError("Change the dataset version before removing a published rule")
            for raw in data["configurations"]:
                values={**raw,"schedule":schedules[raw["schedule"]]}
                obj=VehicleConfiguration(**values);obj.full_clean(validate_unique=False)
                VehicleConfiguration.objects.update_or_create(key=raw["key"],defaults=values)
        except (KeyError,ValueError,TypeError,ValidationError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Imported {len(schedules)} reviewed schedules and {len(data['configurations'])} configurations"))
