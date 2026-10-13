from zoneinfo import available_timezones
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Vehicle, VehicleConfiguration, OdometerReading, ServiceRecord, Appointment, MaintenanceItem, Garage
from .services import applicable_rules

class StyledForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.DateField): field.widget = forms.DateInput(attrs={"type": "date"})

class VehicleForm(StyledForm):
    conditions = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    equipment = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    initial_miles = forms.IntegerField(min_value=0, max_value=3000000, label="Current odometer (miles)")
    reading_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type":"date"}))
    engine_hours = forms.IntegerField(min_value=0, required=False, help_text="Optional. Used for Ford's extensive-idling oil-change limit.")
    assume_maintained = forms.BooleanField(required=False, initial=True,
        label="Assume scheduled maintenance is up to date",
        help_text="Assume required maintenance through this mileage and reading date was completed. Show the next scheduled intervals without creating service records. Uncheck if prior maintenance is unknown.")
    class Meta:
        model = Vehicle
        fields = ["configuration", "nickname", "in_service_date", "conditions", "equipment"]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["configuration"].queryset = VehicleConfiguration.objects.filter(schedule__reviewed=True)
        config = self.instance.configuration if not self.instance._state.adding else None
        if self.is_bound:
            try:
                config = self.fields["configuration"].queryset.filter(pk=self.data.get("configuration") or None).first()
            except (ValueError, TypeError):
                config = None
        if config:
            self.fields["conditions"].choices = list(config.condition_options.items())
            self.fields["equipment"].choices = list(config.equipment_options.items())
        if not self.instance._state.adding:
            for key in ["initial_miles", "reading_date", "engine_hours"]: self.fields.pop(key)
            self.fields["assume_maintained"].initial = self.instance.assumed_through_date is not None
            if self.instance.assumed_through_date:
                self.fields["assume_maintained"].help_text = (
                    f"Prior maintenance is assumed complete through {self.instance.assumed_through_miles:,} miles "
                    f"on {self.instance.assumed_through_date}. This starting point stays fixed as mileage increases. "
                    "Uncheck to remove the assumption. Actual service records and per-item history choices take precedence.")
            else:
                self.fields["assume_maintained"].help_text = "Use the latest mileage reading and its date as the starting point. Actual service records and per-item history choices take precedence."
    def clean_in_service_date(self):
        date = self.cleaned_data["in_service_date"]
        if date and date > timezone.localdate(): raise ValidationError("In-service date cannot be in the future.")
        return date
    def clean_reading_date(self):
        date = self.cleaned_data["reading_date"]
        if date > timezone.localdate(): raise ValidationError("Mileage readings cannot be in the future.")
        return date
    def clean(self):
        data = super().clean()
        config = data.get("configuration")
        if config and not self.instance._state.adding:
            before = self.instance.configuration
            if (config.make, config.model, config.year, config.trim) != (before.make, before.model, before.year, before.trim):
                raise ValidationError("Add a separate vehicle for a different make, model, year or trim so its service history stays separate.")
        if data.get("in_service_date") and data.get("reading_date") and data["in_service_date"] > data["reading_date"]:
            raise ValidationError("The mileage reading cannot predate the original in-service date.")
        if data.get("assume_maintained") and self.instance.assumed_through_date and data.get("in_service_date") and data["in_service_date"] > self.instance.assumed_through_date:
            raise ValidationError("The original in-service date cannot be after the maintenance assumption date.")
        return data

def validate_timeline(vehicle, date, miles, exclude_record=None, exclude_reading=None):
    if date > timezone.localdate(): raise ValidationError("Completed work and mileage readings cannot be in the future.")
    if vehicle.in_service_date and date < vehicle.in_service_date: raise ValidationError("Date is before this vehicle entered service.")
    points = [(r.date, r.miles) for r in vehicle.readings.exclude(pk=exclude_reading)]
    points += [(r.date, r.miles) for r in vehicle.records.exclude(pk=exclude_record)]
    if any(d < date and m > miles or d > date and m < miles for d,m in points):
        raise ValidationError("Mileage conflicts with earlier or later records. Correct the conflicting reading first.")

class ReadingForm(StyledForm):
    class Meta:
        model = OdometerReading
        fields = ["date", "miles", "engine_hours"]
    def __init__(self,*args,vehicle,**kwargs):
        self.vehicle = vehicle
        super().__init__(*args,**kwargs)
    def clean(self):
        data = super().clean()
        if "date" in data and "miles" in data: validate_timeline(self.vehicle, data["date"], data["miles"], exclude_reading=self.instance.pk)
        return data

class RecordForm(StyledForm):
    class Meta:
        model = ServiceRecord
        fields = ["item", "date", "miles", "engine_hours", "cost", "provider", "notes"]
    def __init__(self,*args,vehicle,**kwargs):
        self.vehicle = vehicle
        super().__init__(*args,**kwargs)
        ids = [r.item_id for r in applicable_rules(vehicle)]
        if not self.instance._state.adding: ids.append(self.instance.item_id)
        self.fields["item"].queryset = MaintenanceItem.objects.filter(pk__in=ids).order_by("name")
    def clean(self):
        data = super().clean()
        if "date" in data and "miles" in data: validate_timeline(self.vehicle,data["date"],data["miles"],exclude_record=self.instance.pk)
        return data

class CompletionForm(forms.Form):
    items = forms.ModelMultipleChoiceField(queryset=MaintenanceItem.objects.none(), widget=forms.MultipleHiddenInput)
    miles = forms.IntegerField(min_value=0, max_value=3000000, label="Odometer at service (miles)")
    date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}), label="Service date")
    engine_hours = forms.IntegerField(min_value=0, max_value=2147483647, required=False, label="Engine hours at service (optional)")
    token = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, vehicle, **kwargs):
        super().__init__(*args, **kwargs)
        rules = applicable_rules(vehicle)
        self.fields["items"].queryset = MaintenanceItem.objects.filter(pk__in=[r.item_id for r in rules]).order_by("name")
        values = self.data if self.is_bound else self.initial
        selected_ids = values.getlist("items") if hasattr(values, "getlist") else values.get("items", [])
        selected_ids = {str(value) for value in selected_ids}
        if not any(r.hours and str(r.item_id) in selected_ids for r in rules):
            self.fields.pop("engine_hours")
        # Timeline validation happens under the completion transaction, after
        # checking the receipt. A retry must survive later history edits.


class AppointmentForm(StyledForm):
    class Meta:
        model = Appointment
        fields = ["title", "date", "items", "notes", "cancelled"]
        widgets = {"items": forms.CheckboxSelectMultiple}
    def __init__(self,*args,vehicle,**kwargs):
        super().__init__(*args,**kwargs)
        ids = [r.item_id for r in applicable_rules(vehicle)]
        if not self.instance._state.adding: ids += list(self.instance.items.values_list("id",flat=True))
        self.fields["items"].queryset = MaintenanceItem.objects.filter(pk__in=ids).order_by("name")

class GarageForm(StyledForm):
    class Meta:
        model = Garage
        fields = ["name", "timezone"]
    def clean_timezone(self):
        value = self.cleaned_data["timezone"]
        if value not in available_timezones(): raise ValidationError("Enter an IANA timezone, for example America/New_York.")
        return value
