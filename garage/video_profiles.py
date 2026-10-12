"""Search vocabulary, not maintenance instructions or manufacturer intervals.

Matching deliberately requires positive evidence. No neighboring-year mechanical
compatibility has been reviewed: only a stated year/range including the target
year qualifies. Bump this version when changing vocabulary or matching policy.
"""
from dataclasses import dataclass

PROFILE_VERSION = 3


@dataclass(frozen=True)
class SearchProfile:
    phrases: tuple[str, str]
    component: str
    action: str
    dimensions: tuple[str, ...] = ()
    conflicts: str = r"(?!)"


INSPECT = r"\b(?:inspect\w*|check\w*|test\w*|diagnos\w*|measure\w*)\b"
REPLACE = r"\b(?:replac\w*|chang\w*|renew\w*|drain\w*|flush\w*|bleed\w*|install\w*)\b"
PROFILES = {}


def add(key, phrases, component, action=INSPECT, dimensions=(), conflicts=r"(?!)"):
    PROFILES[key] = SearchProfile(tuple(phrases), component, action, dimensions, conflicts)


add('oil', ('engine oil and filter change', 'how to replace oil and oil filter'), r'\b(?:engine oil|motor oil|oil (?:and filter|filter|change)|chang\w* (?:the )?oil)\b', REPLACE, ('engine',), r'\b(?:transmission|cvt|differential|gear oil|oil filter housing|oil cooler|oil pump|oil pan replacement)\b')
add('tires', ('how to rotate tires and check wear', 'tire rotation tutorial'), r'\btires?\b', r'\b(?:rotat\w*)\b', ('drivetrain',))
add('air', ('engine air filter replacement', 'how to change engine air filter'), r'\b(?:engine air|air intake|air cleaner|air) filter\b', REPLACE, ('engine',), r'\b(?:cabin|pollen)\b')
add('air-check', ('inspect engine air filter', 'how to check engine air filter'), r'\b(?:engine air|air intake|air cleaner|air) filter\b', INSPECT, ('engine',), r'\b(?:cabin|pollen)\b')
add('cabin', ('cabin air filter replacement', 'how to change pollen filter'), r'\b(?:cabin(?: air)?|pollen) filter\b', REPLACE)
add('cabin-check', ('inspect cabin air filter', 'how to check pollen filter'), r'\b(?:cabin(?: air)?|pollen) filter\b')
add('coolant', ('engine coolant replacement', 'coolant drain and refill tutorial'), r'\b(?:coolant|antifreeze|radiator fluid)\b', REPLACE, ('engine',), r'\b(?:water pump|coolant pump|thermostat|radiator cap|coolant reservoir)\b')
add('plugs', ('spark plug replacement', 'how to change spark plugs'), r'\bspark plugs?\b', REPLACE, ('engine',))
add('brakes', ('inspect brake pads and rotors', 'how to check brake wear'), r'\b(?:brakes?|brake pads?|rotors?|brake discs?)\b')
add('brake-lines', ('inspect brake lines and parking brake', 'how to check brake hoses'), r'\b(?:brake (?:lines?|hoses?)|parking brake|service brake)\b')
add('brake-fluid', ('brake fluid replacement bleeding', 'how to change brake fluid'), r'\bbrake fluid\b', REPLACE)
add('brake-fluid-check', ('inspect brake fluid', 'how to test brake fluid'), r'\bbrake fluid\b')
add('boots', ('inspect CV boots and joints', 'how to check axle boots'), r'\b(?:cv|axle) (?:boots?|joints?)\b', INSPECT, ('drivetrain',))
add('steering', ('inspect steering and suspension', 'how to check suspension joints'), r'\b(?:steering|suspension|tie rods?|ball joints?)\b')
add('cooling', ('inspect cooling system hoses', 'how to check radiator hoses'), r'\b(?:cooling system|radiator hoses?|coolant hoses?)\b', INSPECT, ('engine',))
add('fuel-lines', ('inspect fuel lines and connections', 'how to check fuel hoses'), r'\bfuel (?:lines?|hoses?|connections?)\b', INSPECT, ('engine',))
add('evap', ('inspect fuel vapor hoses', 'how to check EVAP hoses'), r'\b(?:fuel vapou?r|evap) (?:hoses?|lines?|system)\b', INSPECT, ('engine',))
add('exhaust', ('inspect exhaust system', 'how to check exhaust leaks'), r'\bexhaust\b', INSPECT, ('engine',))
for key, action, verb in [('belts', INSPECT, 'inspect'), ('belts-replace', REPLACE, 'replace')]:
    add(key, (f'{verb} serpentine belt', f'how to {verb} accessory drive belt'), r'\b(?:serpentine|accessory(?: drive)?|drive) belts?\b', action, ('engine',), r'\b(?:timing|seat) belt\b')
for key, component, phrase, dims, conflicts in [
    ('cvt', r'\b(?:cvt|continuously variable transmission) (?:fluid|oil)\b', 'CVT fluid', ('engine', 'transmission'), r'\b(?:manual transmission|6r80|dsg)\b'),
    ('at', r'\b(?:(?:automatic transmission|transmission|6r80) (?:fluid|oil)|atf)\b', 'automatic transmission fluid', ('transmission',), r'\b(?:cvt|manual transmission|dsg)\b'),
    ('mt', r'\bmanual (?:transmission|gearbox) (?:fluid|oil)\b', 'manual transmission oil', ('transmission',), r'\b(?:cvt|automatic transmission)\b'),
]:
    check_key = {'at': 'at-check', 'mt': 'mt-fluid'}.get(key, key)
    replace_key = {'at': 'at-fluid', 'mt': 'mt-replace'}.get(key, key + '-replace')
    add(check_key, (f'how to check {phrase}', f'{phrase} inspection'), component, INSPECT, dims, conflicts)
    add(replace_key, (f'how to change {phrase}', f'{phrase} drain and refill'), component, REPLACE, dims, conflicts)
add('diff', ('inspect front and rear differential oil', 'check front and rear differential fluid'), r'\b(?:differential|diff) (?:oil|fluid)\b', INSPECT, ('transmission', 'drivetrain'))
add('diff-replace', ('front and rear differential fluid replacement', 'change front and rear differential oil'), r'\b(?:differential|diff) (?:oil|fluid)\b', REPLACE, ('transmission', 'drivetrain'))
add('front-diff', ('front differential fluid change', 'replace front axle oil'), r'\bfront (?:differential|diff|axle)\b', REPLACE, ('drivetrain',), r'\brear (?:differential|diff|axle)\b')
add('rear-diff', ('rear differential fluid change', 'replace rear axle lubricant'), r'\brear (?:differential|diff|axle)\b', REPLACE, ('drivetrain',), r'\bfront (?:differential|diff|axle)\b')
add('transfer', ('transfer case fluid change', 'replace transfer case oil'), r'\btransfer case\b', REPLACE, ('transmission', 'drivetrain'))
add('ujoints', ('inspect driveshaft U joints', 'how to check universal joints'), r'\b(?:u joints?|universal joints?|driveshaft)\b', INSPECT, ('drivetrain',))
add('wheel', ('inspect wheels and lug nuts', 'how to check wheels for damage'), r'\b(?:wheels?|lug nuts?)\b')
add('wheel-bearing', ('inspect wheel bearings', 'how to check wheel bearing play'), r'\bwheel bearings?\b')
add('seat-filter', ('climate controlled seat filter replacement', 'how to change ventilated seat filters'), r'\b(?:seat|seats) (?:air )?filters?\b', REPLACE)
add('fuel-filter', ('fuel filter replacement', 'how to change fuel filter'), r'\bfuel filter\b', REPLACE, ('engine',))
add('multi', ('how to perform multi point inspection', 'vehicle multi point inspection tutorial'), r'\bmulti point inspection\b')
add('lights', ('check exterior and interior lights', 'how to inspect vehicle lights'), r'\b(?:lights?|lamps?)\b')
add('pressure', ('check tire pressure including spare', 'how to measure tire pressure'), r'\btires? pressure\b')
add('oil-level', ('how to check engine oil level', 'engine oil dipstick inspection'), r'\b(?:engine oil|oil level|oil dipstick)\b', INSPECT, ('engine',), r'\b(?:transmission|cvt|differential)\b')
add('washer', ('check windshield washer fluid', 'how to inspect washer fluid level'), r'\b(?:windshield )?washer fluid\b')
add('belts-latches', ('inspect seat belts and latches', 'how to check seat belt buckles'), r'\bseat (?:belts?|latches?)\b')
add('spare', ('inspect spare tire mounting', 'how to check spare tire carrier'), r'\bspare (?:tire|wheel)\b')
add('power-steering', ('check power steering fluid level', 'how to inspect power steering fluid'), r'\bpower steering fluid\b', INSPECT, ('engine',))
add('wipers', ('inspect wipers and washers', 'how to check windshield wipers'), r'\b(?:wipers?|windshield washers?)\b')
add('locks', ('lubricate door hinges locks weatherstrips', 'how to lubricate door hinges and locks'), r'\b(?:door hinges?|door locks?|weatherstrips?)\b', r'\blubricat\w*\b')
add('drains', ('inspect body and door drains', 'how to check door drain holes'), r'\b(?:body|door) drain\w*\b')
add('warning-lights', ('check dashboard warning lamps', 'how to test safety warning lights'), r'\b(?:warning (?:lights?|lamps?)|dashboard lights?)\b')
add('coolant-level', ('check coolant level and strength', 'how to test antifreeze strength'), r'\b(?:coolant|antifreeze)\b', INSPECT, ('engine',))
add('battery', ('inspect battery terminals', 'how to check battery connections'), r'\bbattery (?:terminals?|connections?)\b')
add('valves', ('inspect valve clearance', 'how to measure valve lash'), r'\bvalve (?:clearance|lash)\b', INSPECT, ('engine',))
add('radiator-cap', ('radiator cap replacement', 'how to replace radiator cap'), r'\bradiator cap\b', REPLACE, ('engine',))
add('wipers-replace', ('wiper blade replacement', 'how to change windshield wipers'), r'\bwiper(?:s| blades?)?\b', REPLACE)
add('e85', ('how to fill gasoline when using E85', 'E85 flex fuel gasoline fill tutorial'), r'\b(?:e85|flex fuel)\b', r'\b(?:fill\w*|refuel\w*)\b', ('engine',))
