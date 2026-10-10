from django.urls import path
from . import views as v
urlpatterns=[
path("",v.home,name="home"),path("start/",v.start,name="start"),path("recover/",v.recover,name="recover"),
path("settings/",v.settings_view,name="garage-settings"),path("forget/",v.forget,name="forget"),
path("vehicles/new/",v.vehicle_form,name="vehicle-add"),path("vehicles/<uuid:pk>/",v.vehicle_detail,name="vehicle-detail"),
path("vehicles/<uuid:pk>/edit/",v.vehicle_form,name="vehicle-edit"),path("vehicles/<uuid:pk>/delete/",v.vehicle_delete,name="vehicle-delete"),
path("vehicles/<uuid:pk>/mileage/",v.reading_form,name="reading-add"),path("vehicles/<uuid:pk>/mileage/<int:reading_id>/",v.reading_form,name="reading-edit"),
path("vehicles/<uuid:pk>/records/new/",v.record_form,name="record-add"),path("vehicles/<uuid:pk>/records/<uuid:record_id>/",v.record_form,name="record-edit"),path("vehicles/<uuid:pk>/records/<uuid:record_id>/delete/",v.record_delete,name="record-delete"),
path("vehicles/<uuid:pk>/original/<int:item_id>/",v.original,name="original"),
path("vehicles/<uuid:pk>/appointments/new/",v.appointment_form,name="appointment-add"),path("vehicles/<uuid:pk>/appointments/<uuid:appointment_id>/",v.appointment_detail,name="appointment-detail"),path("vehicles/<uuid:pk>/appointments/<uuid:appointment_id>/edit/",v.appointment_form,name="appointment-edit"),path("vehicles/<uuid:pk>/appointments/<uuid:appointment_id>/calendar/",v.calendar_download,name="calendar-download"),
path("vehicles/<uuid:pk>/history.csv",v.history_csv,name="history-csv"),path("vehicles/<uuid:pk>/videos/<int:item_id>/",v.video_results,name="videos"),
path("health/live",v.health),path("health/ready",v.ready),
]
