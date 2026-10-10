import uuid
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

class Garage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, default="My garage")
    timezone = models.CharField(max_length=80, default="America/New_York")
    recovery_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class SourceDocument(models.Model):
    key = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    sha256 = models.CharField(max_length=64)
    publication = models.CharField(max_length=200)
    def __str__(self): return self.title

class ScheduleVersion(models.Model):
    key = models.SlugField(unique=True)
    version = models.CharField(max_length=30)
    source = models.ForeignKey(SourceDocument, on_delete=models.PROTECT)
    reviewed = models.BooleanField(default=False)
    reviewed_on = models.DateField(null=True)
    review_notes = models.TextField(blank=True)
    def __str__(self): return f"{self.key} / {self.version}"

class VehicleConfiguration(models.Model):
    key = models.SlugField(unique=True)
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=60)
    year = models.PositiveIntegerField()
    trim = models.CharField(max_length=60)
    engine = models.CharField(max_length=60)
    transmission = models.CharField(max_length=60)
    drivetrain = models.CharField(max_length=30)
    schedule = models.ForeignKey(ScheduleVersion, on_delete=models.PROTECT)
    condition_options = models.JSONField(default=dict, blank=True)
    equipment_options = models.JSONField(default=dict, blank=True)
    class Meta:
        ordering = ["make", "model", "year", "trim", "drivetrain"]
    def __str__(self): return f"{self.year} {self.make} {self.model} {self.trim} · {self.engine} · {self.transmission} · {self.drivetrain}"

class MaintenanceItem(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=150)
    action = models.CharField(max_length=20, choices=[("replace", "Replace"), ("inspect", "Inspect"), ("perform", "Perform")])
    search_phrase = models.CharField(max_length=180)
    def __str__(self): return self.name

class MaintenanceRule(models.Model):
    key = models.CharField(max_length=120)
    schedule = models.ForeignKey(ScheduleVersion, on_delete=models.CASCADE, related_name="rules")
    item = models.ForeignKey(MaintenanceItem, on_delete=models.PROTECT)
    miles = models.PositiveIntegerField(null=True, blank=True)
    months = models.PositiveIntegerField(null=True, blank=True)
    hours = models.PositiveIntegerField(null=True, blank=True)
    first_miles = models.PositiveIntegerField(null=True, blank=True)
    first_months = models.PositiveIntegerField(null=True, blank=True)
    basis = models.CharField(max_length=20, choices=[("service", "Since last service"), ("milestone", "Vehicle milestones"), ("conditional", "As needed")], default="milestone")
    conditions_any = models.JSONField(default=list, blank=True)
    conditions_none = models.JSONField(default=list, blank=True)
    equipment_all = models.JSONField(default=list, blank=True)
    drivetrain = models.CharField(max_length=30, blank=True)
    transmission = models.CharField(max_length=60, blank=True)
    priority = models.PositiveIntegerField(default=0)
    optional = models.BooleanField(default=False)
    page = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["schedule", "key"], name="unique_schedule_rule")]
    def __str__(self): return f"{self.schedule.key}: {self.item}"

class Vehicle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    garage = models.ForeignKey(Garage, on_delete=models.CASCADE, related_name="vehicles")
    configuration = models.ForeignKey(VehicleConfiguration, on_delete=models.PROTECT)
    nickname = models.CharField(max_length=80, blank=True)
    in_service_date = models.DateField(null=True, blank=True)
    conditions = models.JSONField(default=list, blank=True)
    equipment = models.JSONField(default=list, blank=True)
    original_items = models.ManyToManyField(MaintenanceItem, blank=True, related_name="original_vehicles")
    unknown_items = models.ManyToManyField(MaintenanceItem, blank=True, related_name="unknown_vehicles")
    assumed_through_date = models.DateField(null=True, blank=True)
    assumed_through_miles = models.PositiveIntegerField(null=True, blank=True)
    assumed_through_hours = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.nickname or f"{self.configuration.year} {self.configuration.make} {self.configuration.model}"
    @property
    def latest_reading(self):
        points = [self.readings.order_by("-date", "-miles").first(), self.records.order_by("-date", "-miles").first()]
        return max((p for p in points if p is not None), key=lambda p: (p.date, p.miles), default=None)

class OdometerReading(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="readings")
    date = models.DateField(default=timezone.localdate)
    miles = models.PositiveIntegerField()
    engine_hours = models.PositiveIntegerField(null=True, blank=True)
    class Meta:
        ordering = ["-date", "-id"]

class ServiceRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="records")
    item = models.ForeignKey(MaintenanceItem, on_delete=models.PROTECT)
    date = models.DateField(default=timezone.localdate)
    miles = models.PositiveIntegerField()
    engine_hours = models.PositiveIntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, validators=[MinValueValidator(0)])
    provider = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True, max_length=5000)
    class Meta:
        ordering = ["-date", "-miles"]

class Appointment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="appointments")
    items = models.ManyToManyField(MaintenanceItem)
    date = models.DateField()
    title = models.CharField(max_length=120)
    notes = models.TextField(blank=True, max_length=5000)
    cancelled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["date"]
    def __str__(self): return self.title

class VideoSearchCache(models.Model):
    key = models.CharField(max_length=64, unique=True)
    results = models.JSONField(default=list, blank=True)
    fetched_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True)
    lease_until = models.DateTimeField(null=True)

class UsageCounter(models.Model):
    key = models.CharField(max_length=180, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
