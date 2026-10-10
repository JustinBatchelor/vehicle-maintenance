"""Reproduce the reviewed, factual schedule dataset. See data/REVIEW.md."""
import json
from pathlib import Path

items = {}
def item(key, name, action="inspect", phrase=None):
    items[key] = dict(key=key, name=name, action=action, search_phrase=phrase or f"{name} {action} how to")
for key,name,action in [
    ("oil","Engine oil and filter","replace"),("tires","Tire rotation and wear check","perform"),
    ("air","Engine air filter","replace"),("air-check","Engine air filter inspection","inspect"),
    ("cabin","Cabin air filter","replace"),("cabin-check","Cabin air filter inspection","inspect"),
    ("coolant","Engine coolant","replace"),("plugs","Spark plugs","replace"),
    ("brakes","Brake pads, discs and hardware","inspect"),("brake-lines","Brake lines and parking/service brake operation","inspect"),
    ("brake-fluid","Brake fluid","replace"),("brake-fluid-check","Brake fluid inspection","inspect"),("boots","Axle boots and joints","inspect"),
    ("steering","Steering and suspension","inspect"),("cooling","Cooling system and hoses","inspect"),
    ("fuel-lines","Fuel lines and connections","inspect"),("evap","Fuel vapor hoses","inspect"),
    ("exhaust","Exhaust system","inspect"),("belts","Accessory drive belts","inspect"),
    ("belts-replace","Accessory drive belt replacement","replace"),("cvt","CVT fluid","inspect"),
    ("cvt-replace","CVT fluid replacement","replace"),("at-fluid","Automatic transmission fluid and filter","replace"),
    ("at-check","Automatic transmission fluid level","inspect"),("mt-fluid","Manual transmission oil","inspect"),
    ("mt-replace","Manual transmission oil replacement","replace"),("diff","Front and rear differential oil","inspect"),
    ("diff-replace","Front and rear differential oil replacement","replace"),("front-diff","Front differential fluid","replace"),
    ("rear-diff","Rear axle lubricant","replace"),("transfer","Transfer case fluid","replace"),
    ("ujoints","Driveshaft U-joints","inspect"),("wheel","Wheels and related components","inspect"),
    ("wheel-bearing","Wheel bearings","inspect"),("seat-filter","Climate-controlled seat filters","replace"),
    ("fuel-filter","Fuel filter","replace"),("multi","Multi-point inspection","inspect"),
    ("lights","Exterior and interior lights","inspect"),("pressure","Tire pressure including spare","inspect"),
    ("oil-level","Engine oil level","inspect"),("washer","Windshield washer fluid","inspect"),
    ("belts-latches","Seat belts and seat latches","inspect"),("spare","Spare tire mounting","inspect"),
    ("power-steering","Power steering fluid level","inspect"),("wipers","Wipers and washer operation","inspect"),
    ("locks","Door hinges, locks and weatherstrips","perform"),("drains","Body and door drains","inspect"),
    ("warning-lights","Safety warning lamps","inspect"),("coolant-level","Coolant level and strength","inspect"),
    ("battery","Battery connections","inspect"),("valves","Valve clearance when noise increases","inspect"),
    ("radiator-cap","Radiator cap","replace"),("wipers-replace","Wiper blades","replace"),
    ("e85","Gasoline fill when running exclusively on E85","perform")]: item(key,name,action)

sources = [
dict(key="ford-2010",title="2010 Ford Scheduled Maintenance Guide",publication="2nd printing, USA",url="https://www.fordservicecontent.com/Ford_Content/catalog/owner_guides/10frdmg2e.pdf",sha256="575226aaf03dec403c716e3c25a14925a389991af077c7a902a4c8b5f26513d9"),
dict(key="nissan-2012",title="2012 Nissan Service and Maintenance Guide",publication="2012 US maintenance booklet",url="https://owners.nissanusa.com/content/techpub/common/2012/2012-nissan-service-maintenance-guide.pdf",sha256="37a6b9425a73ffa0c59b9f71b00471c7a9dc202dc7fcda6259da8f75dd78231e"),
dict(key="subaru-2021",title="2021 Subaru Warranty and Maintenance Booklet",publication="MSA5M2101W, US",url="https://techinfo.subaru.com/stis/doc/warrantyBooklet/2021_war_and_maint__081120.pdf",sha256="11afb9c2faaf27e068fd162c4f4315f187e6599d38c714374389de49f23b7984")]
schedules=[]; configs=[]
def schedule(key, source, notes):
    s=dict(key=key,version="2026.10.09.2",source=source,reviewed=True,reviewed_on="2026-10-09",review_notes=notes,rules=[])
    schedules.append(s);return s
def rule(s,key,miles=None,months=None,page=1,**kw):
    s["rules"].append(dict(key=f"{key}-{len(s['rules'])}",item=key,miles=miles,months=months,page=page,**kw))
def config(key,make,model,year,trim,engine,transmission,drive,s,conditions,equipment=None):
    configs.append(dict(key=key,make=make,model=model,year=year,trim=trim,engine=engine,transmission=transmission,drivetrain=drive,schedule=s["key"],condition_options=conditions,equipment_options=equipment or {}))

f=schedule("f150-2010","ford-2010","Truck schedule pp.14–27, special conditions pp.41–45, axle exception p.47. 6R80 excludes severe 30k ATF change. No scheduled F-150 fuel-filter replacement. Pages are PDF page numbers.")
fc={"towing":"Frequent towing / camper / carrier", "idling":"Extensive idling or low-speed commercial operation", "dust":"Dusty roads", "offroad":"Off-road operation", "e85":"E85 fuel at least half the time", "submerged":"Axle has been submerged"}
fe={"cabin_filter":"Cabin filter actually fitted (not assumed)", "seat_filter":"Climate-controlled seat filters fitted", "at_dipstick":"Transmission has an underhood dipstick", "grease_fittings":"Lubrication fittings fitted"}
for drive in ["4x2","4x4"]: config("ford-f150-2010-"+drive,"Ford","F-150",2010,"King Ranch","5.4L V8","6R80 automatic",drive,f,fc,fe)
severe=["towing","idling","dust","offroad","e85"]
rule(f,"oil",7500,6,5,basis="service")
rule(f,"oil",5000,6,41,basis="service",conditions_any=severe,priority=10)
rule(f,"oil",5000,6,42,basis="service",hours=200,conditions_any=["idling"],priority=20,notes="Also limited to 200 engine hours; record engine hours to evaluate this limit.")
for key in ["tires","wheel"]:
    rule(f,key,7500,page=14)
    rule(f,key,5000,page=41,conditions_any=severe,priority=10)
for key in ["steering","cooling","brakes","brake-lines","boots","exhaust"]: rule(f,key,15000,page=14)
rule(f,"brakes",5000,page=42,conditions_any=["idling"],priority=10)
rule(f,"at-check",15000,page=14,equipment_all=["at_dipstick"])
rule(f,"ujoints",15000,page=14,drivetrain="4x4",notes="Inspect; lubricate only joints fitted with lubrication points.")
rule(f,"ujoints",5000,6,41,conditions_any=["towing","idling","dust"],priority=10,notes="Inspect and lubricate applicable joints; inspect more frequently under towing.")
rule(f,"ujoints",page=45,basis="conditional",conditions_any=["offroad"],priority=20,notes="Check frequently after off-road operation; lubricate only if fittings exist.")
rule(f,"air",30000,page=16)
rule(f,"air-check",page=44,basis="conditional",conditions_any=["dust"],notes="Inspect frequently and replace as required in dusty operation.")
rule(f,"cabin-check",7500,page=14,equipment_all=["cabin_filter"])
rule(f,"cabin",15000,page=14,equipment_all=["cabin_filter"])
rule(f,"seat-filter",30000,page=16,equipment_all=["seat_filter"])
rule(f,"plugs",90000,page=22)
rule(f,"plugs",60000,page=42,conditions_any=["idling"],priority=10)
rule(f,"coolant",45000,36,5,first_miles=105000,first_months=72,basis="service",notes="First replacement at 105,000 mi / 6 years; subsequent replacements every 45,000 mi / 3 years.")
rule(f,"belts",30000,page=22,first_miles=90000)
rule(f,"belts-replace",page=27,basis="conditional",notes="At 150,000 miles replace if not replaced within the previous 100,000 miles. Inspect for wear between replacements.")
rule(f,"at-fluid",150000,page=27,notes="6R80: normal 150,000-mile service applies; the severe-use 30,000-mile ATF rule explicitly excludes 6R80.")
rule(f,"transfer",150000,page=27,drivetrain="4x4")
rule(f,"transfer",60000,page=41,conditions_any=["towing","dust","offroad"],drivetrain="4x4",priority=10)
rule(f,"front-diff",150000,page=27,drivetrain="4x4")
rule(f,"rear-diff",page=47,basis="conditional",notes="Ford-design light-truck axles with synthetic lubricant have no routine change interval. Service for leakage/repair or immersion; change lubricant after submersion. Verify axle/lubricant if modified.")
rule(f,"multi",7500,page=14,optional=True)
for key in ["lights","pressure","oil-level","washer"]: rule(f,key,months=1,page=8,basis="service",optional=True)
for key in ["belts-latches","spare","power-steering","wipers","locks","drains","warning-lights","coolant-level","battery"]: rule(f,key,months=6,page=8,basis="service",optional=True)
rule(f,"e85",3000,page=45,conditions_any=["e85"],basis="service",notes="This gasoline-fill interval applies only when otherwise operating exclusively on E85.")

n=schedule("altima-2012","nissan-2012","Schedules 1/2 only; Premium entries marked optional. PDF page = printed page + 2. CVT severe replacement uses the specific p.12 exception, not generic automatic-transmission footnotes.")
nc={"short":"Repeated trips under 5 miles (10 in freezing weather)","traffic":"Hot stop-and-go traffic / extended low speeds", "dust":"Dusty roads", "rough":"Rough, muddy or salt-spread roads", "towing":"Trailer, camper or car-top carrier"}
for trans,slug in [("CVT","cvt"),("6-speed manual (coupe)","manual-coupe")]: config("nissan-altima-2012-"+slug,"Nissan","Altima",2012,"3.5 SR","3.5L V6",trans,"FWD",n,nc)
ns=list(nc)
rule(n,"oil",7500,6,11,basis="service")
rule(n,"oil",3750,3,11,basis="service",conditions_any=ns,priority=10)
rule(n,"tires",7500,6,19)
for key in ["brakes","boots"]:
    rule(n,key,15000,12,23)
    rule(n,key,7500,6,19,conditions_any=ns,priority=10)
for key in ["steering","exhaust"]:
    rule(n,key,30000,24,28)
    rule(n,key,7500,6,19,conditions_any=ns,priority=10)
rule(n,"brake-lines",15000,12,23)
rule(n,"brake-fluid",30000,24,28)
rule(n,"brake-fluid",15000,12,23,conditions_any=ns,priority=10)
rule(n,"cabin",15000,12,23,notes="Replace more frequently with prolonged dust exposure.")
rule(n,"air",30000,24,28)
rule(n,"air-check",page=12,basis="conditional",conditions_any=["dust"],notes="Check and replace more frequently in prolonged dusty driving.")
for key in ["fuel-lines","evap"]: rule(n,key,30000,24,28)
rule(n,"belts",15000,12,38,first_miles=60000,first_months=48)
rule(n,"plugs",105000,84,51)
rule(n,"coolant",75000,60,12,basis="service",first_miles=105000,first_months=84,notes="Factory blue coolant: first 105,000 mi / 7 years; then 75,000 mi / 5 years. Other coolant mixtures can shorten this interval.")
rule(n,"cvt",15000,12,23,transmission="CVT")
rule(n,"cvt-replace",page=14,basis="conditional",transmission="CVT",conditions_any=["towing","rough"],notes="At 60,000 miles replace CVT fluid OR ask a dealer to check deterioration data; replace if over 210000. Do not apply generic 30k automatic-fluid rule to this CVT exception.")
rule(n,"mt-fluid",15000,12,23,transmission="6-speed manual (coupe)")
rule(n,"mt-replace",30000,24,14,transmission="6-speed manual (coupe)",conditions_any=["towing","rough"])
rule(n,"valves",page=13,basis="conditional",optional=True,notes="Inspect only when valve noise increases; adjust if needed.")
for key in ["belts-replace","radiator-cap","wipers-replace","locks"]: rule(n,key,30000,24,28,optional=True,notes="Optional Nissan Premium upgrade; not part of the required Schedule 1/2 work.")

s=schedule("crosstrek-2021","subaru-2021","US 2021 table p.28, condition-specific footnotes p.29. Limited 2.5L CVT; excludes STI timing belt, BRZ, hybrid and manual-only rows. Continue intervals per p.27.")
sc={"short":"Repeated short trips", "rough":"Rough or muddy roads", "dust":"Extremely dusty driving", "cold":"Extremely cold weather", "salt":"Road salt / corrosive material exposure", "coastal":"Coastal environment", "towing":"Repeated trailer towing", "humidity":"High humidity or mountainous areas", "hot":"Extremely hot weather"}
config("subaru-crosstrek-2021-limited","Subaru","Crosstrek",2021,"Limited","2.5L flat-four","CVT","AWD",s,sc)
rule(s,"oil",6000,6,28,basis="service")
rule(s,"oil",3000,3,29,basis="service",conditions_any=["short","cold","towing"],priority=10)
rule(s,"tires",6000,6,28)
rule(s,"plugs",60000,60,28)
for key in ["belts","fuel-lines","air","cooling","cvt","diff","brake-fluid"]: rule(s,key,30000,30,28)
rule(s,"fuel-filter",72000,72,28,notes="More frequent replacement may be needed in extreme heat or cold; inspect contamination. Not required for emissions-warranty eligibility.")
rule(s,"coolant",75000,72,28,basis="service",first_miles=137500,first_months=132,notes="First 137,500 mi / 11 years; then 75,000 mi / 6 years. Follow note 10 on coolant conditioner.")
for key in ["brake-lines","brakes","boots","steering"]: rule(s,key,12000,12,28)
rule(s,"wheel-bearing",60000,60,28)
rule(s,"cabin",12000,12,28)
rule(s,"air-check",page=29,basis="conditional",conditions_any=["dust"],notes="Inspect the air cleaner more frequently under extreme dust; replace as required.")
rule(s,"fuel-lines",6000,6,29,conditions_any=["salt","coastal"],priority=10)
rule(s,"brake-lines",6000,6,29,conditions_any=["rough","salt","towing"],priority=10)
for key in ["brakes","boots"]: rule(s,key,6000,6,29,conditions_any=["cold","salt","towing"],priority=10)
rule(s,"steering",6000,6,29,conditions_any=["cold","towing"],priority=10)
rule(s,"brake-fluid",15000,15,29,conditions_any=["humidity"],priority=10)
rule(s,"brake-fluid-check",6000,6,29,conditions_any=["rough","salt","towing"],notes="Additional severe-use inspection from footnote 6. Does not replace the brake-fluid replacement interval.")
rule(s,"diff-replace",15000,15,29,conditions_any=["towing"])
rule(s,"cvt-replace",24855,page=29,conditions_any=["towing"],basis="service")

data=dict(schema_version=1,sources=sources,items=list(items.values()),schedules=schedules,configurations=configs)
Path(__file__).resolve().parents[1].joinpath("data/schedules.json").write_text(json.dumps(data,indent=2)+"\n")
