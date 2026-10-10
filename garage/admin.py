from django.contrib import admin
from .models import SourceDocument,ScheduleVersion,VehicleConfiguration,MaintenanceItem,MaintenanceRule
for model in [SourceDocument,ScheduleVersion,VehicleConfiguration,MaintenanceItem,MaintenanceRule]:admin.site.register(model)
admin.site.site_header="Garage · schedule administration"
