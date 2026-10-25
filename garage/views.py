import csv
import hashlib
import secrets
import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model
from . import accounts
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.cache import never_cache
from icalendar import Calendar, Event
from .models import Garage, Vehicle, VehicleConfiguration, OdometerReading, ServiceRecord, Appointment, MaintenanceItem, CompletionSubmission
from .forms import VehicleForm, ReadingForm, RecordForm, AppointmentForm, GarageForm, CompletionForm, QuickMileageForm
from .services import recommendations, applicable_rules, maintenance_timeline
from .completions import complete_services
from .mileage import update_current_mileage
from .limits import consume, client_key
from . import videos

def private(view):
    @wraps(view)
    @never_cache
    def wrapped(request,*args,**kwargs):
        if not request.garage:return redirect("account-welcome" if request.google_authenticated else "account_login")
        return view(request,*args,**kwargs)
    return wrapped

def owned_vehicle(request,pk):
    return get_object_or_404(Vehicle.objects.select_related("configuration__schedule__source"),pk=pk,garage=request.garage)

@never_cache
def home(request):
    if request.google_authenticated and not request.garage:return redirect("account-welcome")
    if not request.garage:return render(request,"garage/welcome.html")
    return render_dashboard(request)


def render_dashboard(request, *, mileage_vehicle_id=None, mileage_form=None):
    cars=[]; counts={"overdue":0,"due":0,"due-soon":0,"unknown":0}
    for car in request.garage.vehicles.select_related("configuration__schedule").order_by("created_at"):
        rows=recommendations(car)
        for row in rows:
            status=row["due"].status
            if status in counts and not row["rule"].optional:counts[status]+=1
        reading = car.latest_reading
        form = mileage_form if car.pk == mileage_vehicle_id else QuickMileageForm(
            initial={"miles": reading.miles if reading else None}, vehicle_id=car.pk)
        cars.append({"vehicle":car,"reading":reading,"mileage_form":form,"attention":sum(r["due"].status in ["overdue","due","due-soon"] and not r["rule"].optional for r in rows)})
    appointments=Appointment.objects.filter(vehicle__garage=request.garage,cancelled=False,date__gte=timezone.localdate()).select_related("vehicle__configuration")[:5]
    return render(request,"garage/dashboard.html",{"cars":cars,"counts":counts,"appointments":appointments,"mileage_date":timezone.localdate()})

@require_POST
def start(request):
    if request.google_authenticated:return redirect("account-welcome")
    if settings.GOOGLE_AUTH_REQUIRED:return redirect("account_login")
    if request.garage:return redirect("home")
    if not consume("start:"+client_key(request),10,3600):return HttpResponse("Too many new garages. Please try later.",status=429)
    garage=Garage.objects.create()
    request.session.cycle_key()
    request.session["garage_id"]=str(garage.pk)
    messages.success(request,"Your private garage is ready. Save a recovery code in Garage settings to use another device.")
    return redirect("vehicle-add")

@never_cache
def recover(request):
    if settings.GOOGLE_AUTH_REQUIRED or request.google_authenticated:return redirect("garage-import")
    if request.method=="POST":
        if not consume("recover:"+client_key(request),10,900):return HttpResponse("Too many attempts. Try again in 15 minutes.",status=429)
        token=request.POST.get("code","").strip()
        garage=Garage.objects.filter(owner__isnull=True,recovery_hash=hashlib.sha256(token.encode()).hexdigest()).first() if token else None
        if garage:
            request.session.flush()
            request.session["garage_id"]=str(garage.pk)
            messages.success(request,"Garage restored on this browser.")
            return redirect("home")
        messages.error(request,"That recovery code was not recognized.")
    return render(request,"garage/recover.html")

@private
def settings_view(request):
    form=GarageForm(request.POST or None,instance=request.garage)
    code=None
    if request.method=="POST":
        if request.POST.get("action")=="recovery" and not request.google_authenticated and not settings.GOOGLE_AUTH_REQUIRED:
            code=secrets.token_urlsafe(32)
            request.garage.recovery_hash=hashlib.sha256(code.encode()).hexdigest()
            request.garage.save(update_fields=["recovery_hash"])
        elif form.is_valid():
            form.save();messages.success(request,"Garage settings saved.");return redirect("garage-settings")
    return render(request,"account/settings.html" if request.google_authenticated else "garage/settings.html",{"form":form,"code":code})

@private
@require_POST
def forget(request):
    return accounts.sign_out(request)


@private
def vehicle_form(request,pk=None):
    car=owned_vehicle(request,pk) if pk else None
    if not car and request.garage.vehicles.count()>=30:return HttpResponse("This garage has reached its 30-vehicle limit.",status=400)
    form=VehicleForm(request.POST or None,instance=car)
    if request.method=="POST" and form.is_valid():
        with transaction.atomic():
            if request.google_authenticated:
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if not car and request.garage.vehicles.count()>=30:return HttpResponse("This garage has reached its 30-vehicle limit.",status=400)
            vehicle=form.save(commit=False);vehicle.garage=request.garage;vehicle.save()
            if not car:
                OdometerReading.objects.create(vehicle=vehicle,miles=form.cleaned_data["initial_miles"],date=form.cleaned_data["reading_date"],engine_hours=form.cleaned_data["engine_hours"])
            if form.cleaned_data["assume_maintained"] and vehicle.assumed_through_date is None:
                reading = vehicle.latest_reading
                if reading:
                    vehicle.assumed_through_date = reading.date
                    vehicle.assumed_through_miles = reading.miles
                    vehicle.assumed_through_hours = reading.engine_hours
            elif not form.cleaned_data["assume_maintained"]:
                vehicle.assumed_through_date = vehicle.assumed_through_miles = vehicle.assumed_through_hours = None
            vehicle.save(update_fields=["assumed_through_date", "assumed_through_miles", "assumed_through_hours"])
        messages.success(request,"Vehicle saved. Previous work can be added using Log service.")
        return redirect("vehicle-detail",pk=vehicle.pk)
    catalog=list(VehicleConfiguration.objects.filter(schedule__reviewed=True).values("id","make","model","year","trim","engine","transmission","drivetrain","condition_options","equipment_options"))
    return render(request,"garage/vehicle_form.html",{"form":form,"catalog":catalog,"vehicle":car})

@private
def vehicle_detail(request,pk):
    car=owned_vehicle(request,pk)
    return render_vehicle(request, car)


def render_vehicle(request, car, *, mileage_form=None, maintenance_view=None):
    rows=recommendations(car)
    reading=car.latest_reading
    view = maintenance_view if maintenance_view is not None else request.GET.get("view")
    return render(request,"garage/vehicle.html",{"vehicle":car,"reading":reading,"rows":rows,
        "maintenance_view": "list" if view == "list" else "timeline",
        "mileage_form": mileage_form if mileage_form is not None else QuickMileageForm(initial={"miles": reading.miles if reading else None}),
        "mileage_date": timezone.localdate(),
        "timeline": maintenance_timeline(rows, reading),
        "records":car.records.select_related("item"),"appointments":car.appointments.prefetch_related("items")})


@private
@require_http_methods(["GET", "POST"])
def complete_service(request, pk):
    car = owned_vehicle(request, pk)
    reading = car.latest_reading
    initial = {"items": request.GET.getlist("items"), "miles": reading.miles if reading else None,
               "date": timezone.localdate(), "token": uuid.uuid4()}
    form = CompletionForm(request.POST if request.method == "POST" else None, vehicle=car, initial=initial)
    selection_error = None
    try:
        selected = form.fields["items"].clean((request.POST if request.method == "POST" else request.GET).getlist("items"))
    except ValidationError:
        selected = []
        selection_error = "Select at least one applicable service from the vehicle page."
    if request.method == "POST" and form.is_valid():
        try:
            receipt, created = complete_services(car, form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        except IntegrityError:
            # A conflicting token on another vehicle can race its unique insert.
            # Other database failures must surface rather than masquerade as input errors.
            if not CompletionSubmission.objects.filter(token=form.cleaned_data["token"]).exists():
                raise
            form.add_error(None, "This submission token is already in use. Start a new completion from the vehicle page.")
        else:
            count = len(receipt.payload["items"])
            messages.success(request, f"{count} service{'s' if count != 1 else ''} recorded. Due dates have been recalculated."
                             if created else "This completion was already saved. No duplicate records were added.")
            url = reverse("vehicle-detail", args=[car.pk])
            if request.headers.get("HX-Request") == "true":
                return HttpResponse(headers={"HX-Redirect": url})
            return redirect(url)
    template = "garage/completion_panel.html" if request.headers.get("HX-Request") == "true" else "garage/completion.html"
    return render(request, template, {"vehicle": car, "reading": reading, "form": form,
                  "selected": selected, "selection_error": selection_error})

@private
def vehicle_delete(request,pk):
    car=owned_vehicle(request,pk)
    if request.method=="POST":
        car.delete();messages.success(request,"Vehicle and its records deleted.");return redirect("home")
    return render(request,"garage/confirm.html",{"object":car,"title":"Delete vehicle and all its history?"})

@private
@require_http_methods(["GET", "POST"])
def reading_form(request,pk,reading_id=None):
    car=owned_vehicle(request,pk)
    if request.method == "POST" and request.POST.get("mode") == "quick" and reading_id is None:
        return_to_garage = request.POST.get("return_to") == "garage"
        form = QuickMileageForm(request.POST, vehicle_id=car.pk if return_to_garage else None)
        if form.is_valid():
            try:
                _, created = update_current_mileage(car, form.cleaned_data["miles"])
            except ValidationError as exc:
                form.add_error("miles", exc)
            else:
                if return_to_garage:
                    messages.success(request, f"{car}: mileage updated. Maintenance status has been recalculated." if created
                                     else f"{car}: this mileage is already recorded for today. Maintenance status is up to date.")
                    return redirect(reverse("home") + f"#vehicle-{car.pk}")
                messages.success(request, "Mileage updated. Maintenance status has been recalculated." if created
                                 else "This mileage is already recorded for today. Maintenance status is up to date.")
                url = reverse("vehicle-detail", args=[car.pk])
                return redirect(url + ("?view=list" if request.POST.get("view") == "list" else ""))
        if return_to_garage:
            return render_dashboard(request, mileage_vehicle_id=car.pk, mileage_form=form)
        return render_vehicle(request, car, mileage_form=form, maintenance_view=request.POST.get("view"))
    # Historical readings/corrections share the same vehicle lock as quick saves.
    if request.method == "POST":
        with transaction.atomic():
            car = Vehicle.objects.select_for_update().get(pk=car.pk, garage=request.garage)
            reading = get_object_or_404(OdometerReading, pk=reading_id, vehicle=car) if reading_id else None
            form = ReadingForm(request.POST, instance=reading, vehicle=car)
            if form.is_valid():
                record = form.save(commit=False)
                record.vehicle = car
                record.save()
                messages.success(request, "Mileage updated. Maintenance status has been recalculated.")
                return redirect("vehicle-detail", pk=car.pk)
        return render(request,"garage/form.html",{"form":form,"title":"Correct mileage reading" if reading else "Update mileage","vehicle":car})
    reading=get_object_or_404(OdometerReading,pk=reading_id,vehicle=car) if reading_id else None
    form=ReadingForm(instance=reading,vehicle=car)
    return render(request,"garage/form.html",{"form":form,"title":"Correct mileage reading" if reading else "Update mileage","vehicle":car})

@private
def record_form(request,pk,record_id=None):
    car=owned_vehicle(request,pk)
    record=get_object_or_404(ServiceRecord,pk=record_id,vehicle=car) if record_id else None
    form=RecordForm(request.POST or None,instance=record,vehicle=car,initial={"item":request.GET.get("item")})
    if request.method=="POST" and form.is_valid():
        row=form.save(commit=False);row.vehicle=car;row.save()
        # Recording historical work must not create a misleading current odometer reading.
        messages.success(request,"Service recorded. Due dates have been recalculated.")
        return redirect("vehicle-detail",pk=car.pk)
    return render(request,"garage/form.html",{"form":form,"title":"Edit service" if record else "Log completed service","vehicle":car})

@private
def record_delete(request,pk,record_id):
    car=owned_vehicle(request,pk);record=get_object_or_404(ServiceRecord,pk=record_id,vehicle=car)
    if request.method=="POST":record.delete();return redirect("vehicle-detail",pk=car.pk)
    return render(request,"garage/confirm.html",{"object":record.item,"title":"Delete this service record?"})

@private
@require_POST
def original(request,pk,item_id):
    car=owned_vehicle(request,pk)
    if item_id not in [r.item_id for r in applicable_rules(car)]:raise Http404
    if car.records.filter(item_id=item_id).exists():
        messages.error(request,"This task already has service history. Edit its records instead.")
    elif request.POST.get("clear"):
        car.original_items.remove(item_id)
        car.unknown_items.add(item_id)
    elif request.POST.get("assume") and car.assumed_through_date:
        car.original_items.remove(item_id)
        car.unknown_items.remove(item_id)
    else:
        car.original_items.add(item_id)
        car.unknown_items.remove(item_id)
        messages.success(request,"Marked as never serviced. First-service limits now apply; no completed work was added.")
    return redirect("vehicle-detail",pk=pk)

@private
def appointment_form(request,pk,appointment_id=None):
    car=owned_vehicle(request,pk)
    appointment=get_object_or_404(Appointment,pk=appointment_id,vehicle=car) if appointment_id else None
    form=AppointmentForm(request.POST or None,instance=appointment,vehicle=car,initial={"items":[request.GET.get("item")] if request.GET.get("item") else []})
    if request.method=="POST" and form.is_valid():
        appointment=form.save(commit=False);appointment.vehicle=car;appointment.save();form.save_m2m()
        messages.success(request,"Appointment saved. Calendar copies are independent; update any previously saved events yourself.")
        return redirect("appointment-detail",pk=car.pk,appointment_id=appointment.pk)
    return render(request,"garage/form.html",{"form":form,"title":"Edit appointment" if appointment else "Plan service","vehicle":car})

def event_text(request,appointment):
    title=f"{appointment.vehicle}: {appointment.title}"
    details="Maintenance: "+", ".join(appointment.items.values_list("name",flat=True))+"\n"+request.build_absolute_uri(reverse("appointment-detail",kwargs={"pk":appointment.vehicle_id,"appointment_id":appointment.pk}))
    return title,details

@private
def appointment_detail(request,pk,appointment_id):
    car=owned_vehicle(request,pk)
    appointment=get_object_or_404(Appointment,pk=appointment_id,vehicle=car)
    title,details=event_text(request,appointment)
    params={"action":"TEMPLATE","text":title,"details":details,"dates":appointment.date.strftime("%Y%m%d")+"/"+(appointment.date+timedelta(days=1)).strftime("%Y%m%d"),"ctz":request.garage.timezone}
    return render(request,"garage/appointment.html",{"vehicle":car,"appointment":appointment,"google_url":"https://calendar.google.com/calendar/render?"+urlencode(params)})

@private
def calendar_download(request,pk,appointment_id):
    car=owned_vehicle(request,pk);a=get_object_or_404(Appointment,pk=appointment_id,vehicle=car,cancelled=False)
    title,details=event_text(request,a)
    cal=Calendar();cal.add("prodid","-//Garage//Maintenance//EN");cal.add("version","2.0")
    event=Event();event.add("uid",f"{a.pk}@garage");event.add("dtstamp",a.updated_at);event.add("dtstart",a.date);event.add("dtend",a.date+timedelta(days=1));event.add("summary",title);event.add("description",details)
    cal.add_component(event)
    response=HttpResponse(cal.to_ical(),content_type="text/calendar; charset=utf-8");response["Content-Disposition"]='attachment; filename="maintenance.ics"';return response

def csv_safe(value):
    text=str(value) if value is not None else ""
    return "'"+text if text.lstrip().startswith(("=","+","-","@")) or text.startswith(("\t","\r")) else text

@private
def history_csv(request,pk):
    car=owned_vehicle(request,pk)
    response=HttpResponse(content_type="text/csv; charset=utf-8");response["Content-Disposition"]='attachment; filename="service-history.csv"'
    writer=csv.writer(response);writer.writerow(["Vehicle","Task","Action","Date","Miles","Cost (USD)","Provider","Notes"])
    for row in car.records.select_related("item"):
        writer.writerow([csv_safe(v) for v in [str(car),row.item.name,row.item.action,row.date,row.miles,row.cost,row.provider,row.notes]])
    return response

@private
def video_results(request,pk,item_id):
    car=owned_vehicle(request,pk)
    ids=[r.item_id for r in applicable_rules(car)]
    if item_id not in ids and not car.appointments.filter(items__id=item_id).exists():raise Http404
    item=get_object_or_404(MaintenanceItem,pk=item_id)
    if not consume("video:"+str(request.garage.pk),30,60):
        data={"videos":[],"outcome":"unavailable","search_url":videos.search_url(car,item),"notice":"Please wait a minute before loading more video cards. You can still search YouTube."}
    else:
        data=videos.discover(car,item)
    return render(request,"garage/videos.html",{**data,"item":item})

def health(request):return JsonResponse({"status":"ok"})
def ready(request):
    try:
        with connection.cursor() as cursor:cursor.execute("SELECT 1")
    except Exception:return JsonResponse({"status":"unavailable"},status=503)
    return JsonResponse({"status":"ready"})
