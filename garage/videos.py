"""Conservative, automatic tutorial discovery with shared caching and quotas."""
import hashlib
import html
import logging
import re
import time
from datetime import timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .limits import consume
from .models import VideoSearchCache
from .video_profiles import PROFILES, PROFILE_VERSION

logger = logging.getLogger(__name__)
SEARCH_VERSION = 3
MATCH_LABEL = 'Possible vehicle and service match'
NOTICES = {
    'matches': '',
    'no_matches': 'No close video matches found for this vehicle and service.',
    'unavailable': 'Video search is unavailable right now. You can still search YouTube.',
    'refreshing': 'Videos are being refreshed. Try again shortly, or search YouTube.',
}


def normalize(text):
    text = html.unescape(text).lower()
    text = re.sub(r'f[\s-]?150\b', 'f150', text)
    text = re.sub(r'\b((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})\b', r'\1 to \2', text)
    return re.sub(r'\s+', ' ', re.sub(r'[^\w.]+', ' ', text)).strip()


def contains(pattern, text):
    return bool(re.search(pattern, text))


def queries(vehicle, item):
    c = vehicle.configuration
    profile = PROFILES.get(item.key)
    dimensions = profile.dimensions if profile else ()
    context = ' '.join([str(c.year), c.make, c.model] + [getattr(c, d) for d in dimensions])
    phrases = profile.phrases if profile else (item.search_phrase,)
    return [(f'{context} {phrase}', MATCH_LABEL) for phrase in phrases]


def search_url(vehicle, item):
    return 'https://www.youtube.com/results?' + urlencode({'search_query': queries(vehicle, item)[0][0]})


def cache_key(vehicle, item):
    c = vehicle.configuration
    context = (SEARCH_VERSION, PROFILE_VERSION, c.key, c.year, c.make, c.model,
               c.engine, c.transmission, c.drivetrain, item.key, item.action,
               PROFILES.get(item.key), queries(vehicle, item))
    return hashlib.sha256(repr(context).encode()).hexdigest()


def evidence_text(snippet, profile):
    """Ignore tags, affiliate lists, chapters and description keyword dumps.

    Titles must name the component. Supporting descriptions must be short
    narrative sentences about demonstrating that component/procedure.
    This conservative heuristic does not verify the video's actual content.
    """
    title = normalize(snippet.get('title', ''))
    if not contains(profile.component, title):
        return ''
    narrative = []
    for line in snippet.get('description', '')[:1500].splitlines()[:8]:
        if len(line) > 400 or contains(r'https?://|#|\||;|\b(tags|keywords):', line.lower()) or line.count(',') > 2:
            continue
        for sentence in re.split(r'(?<=[.!?])\s+', line):
            clean = normalize(sentence)
            if (contains(r'\b(?:in this video|this tutorial|we (?:show|check|inspect|replace|change)|i (?:show|check|inspect|replace|change)|how to|step by step)\b', clean)
                    and contains(profile.component, clean) and contains(profile.action, clean)):
                narrative.append(clean)
    return ' '.join([title, *narrative])


def year_matches(text, target):
    # No implicit neighboring year/generation expansion. A list is not a range.
    ranges = list(re.finditer(r'\b((?:19|20)\d{2})\s+to\s+((?:19|20)\d{2})\b', text))
    years = []
    for match in ranges:
        start, end = map(int, match.groups())
        if not start <= target <= end:
            return False
        years.append(target)
    remainder = text
    for match in reversed(ranges):
        remainder = remainder[:match.start()] + ' ' + remainder[match.end():]
    years.extend(map(int, re.findall(r'\b(?:19|20)\d{2}\b', remainder)))
    return bool(years) and all(year == target for year in years)


def configuration_matches(text, c, dimensions):
    if not contains(r'\b' + re.escape(normalize(c.model)) + r'\b', text):
        return False
    # The model identifies these supported vehicles; make may be absent.
    makes = {'ford', 'nissan', 'subaru', 'honda', 'toyota', 'chevrolet', 'chevy', 'gmc',
             'dodge', 'ram', 'jeep', 'hyundai', 'kia', 'mazda', 'mitsubishi', 'volkswagen', 'bmw', 'audi'}
    if any(contains(r'\b' + make + r'\b', text) for make in makes - {c.make.lower()}):
        return False
    models = {'f150', 'altima', 'crosstrek', 'ascent', 'outback', 'forester', 'impreza', 'legacy',
              'sentra', 'maxima', 'rogue', 'titan', 'frontier', 'mustang', 'explorer', 'expedition', 'f250'}
    if any(contains(r'\b' + model + r'\b', text) for model in models - {normalize(c.model)}):
        return False
    if not year_matches(text, c.year):
        return False
    # None of the reviewed configurations is Raptor, hybrid, diesel or EcoBoost.
    if contains(r'\b(?:raptor|hybrid|diesel|ecoboost)\b', text):
        return False
    # Explicit contradictions always reject. Missing details reject only when
    # the procedure depends on them.
    engine = re.search(r'\d\.\d', c.engine)
    mentioned_engines = re.findall(r'\b(\d\.\d)\s*(?:l(?:iter|itre)?s?)?\b', text)
    if mentioned_engines and (not engine or any(e != engine[0] for e in mentioned_engines)):
        return False
    if 'engine' in dimensions and (not engine or engine[0] not in mentioned_engines):
        return False
    if 'turbo' in c.engine.lower() and contains(r'\b(?:naturally aspirated|non turbo|without (?:a )?turbo)\b', text):
        return False
    cylinder = re.search(r'\b[vh]([468])\b', normalize(c.engine))
    expected_cylinders = cylinder[1] if cylinder else ('4' if 'four' in c.engine.lower() else None)
    if any(n != expected_cylinders for n in re.findall(r'\b[vh]([468])\b', text)):
        return False
    transmission_patterns = {
        'cvt': r'\b(?:cvt|continuously variable)\b',
        'manual': r'\b(?:manual|6 speed)\b',
        '6r80': r'\b6r80\b',
    }
    transmission = c.transmission.lower()
    if 'coupe' in transmission and contains(r'\bsedan\b', text):
        return False
    expected = 'cvt' if 'cvt' in transmission else 'manual' if 'manual' in transmission else '6r80'
    if any(contains(pattern, text) for key, pattern in transmission_patterns.items() if key != expected):
        return False
    if expected != '6r80' and contains(r'\b(?:conventional automatic|dsg)\b', text):
        return False
    if 'transmission' in dimensions and not contains(transmission_patterns[expected], text):
        return False
    drive_patterns = {'AWD': r'\b(?:awd|all wheel drive)\b', 'FWD': r'\b(?:fwd|front wheel drive)\b',
                      '4x4': r'\b(?:4x4|4wd|four wheel drive)\b', '4x2': r'\b(?:4x2|2wd|rwd|rear wheel drive)\b'}
    if any(contains(pattern, text) for key, pattern in drive_patterns.items() if key != c.drivetrain):
        return False
    if 'drivetrain' in dimensions and not contains(drive_patterns.get(c.drivetrain, r'(?!)'), text):
        return False
    return True


def candidate_matches(video, vehicle, item):
    profile = PROFILES.get(item.key)
    if not profile:
        return False
    text = evidence_text(video.get('snippet', {}), profile)
    # Generic calls to action and warning-light names are not service actions.
    action_text = re.sub(r'\bcheck (?:engine (?:light|code)\w*|out|the description)\b', '', text)
    if not text or not contains(profile.action, action_text) or contains(profile.conflicts, text):
        return False
    if contains(r'\b(?:review|for sale|sale price|buy now|discount code|promo code|coupon|unboxing|test drive)\b', text):
        return False
    if item.key in {'diff', 'diff-replace'} and not (contains(r'\bfront\b', text) and contains(r'\brear\b', text)):
        return False
    if item.key == 'at-fluid' and not contains(r'\bfilter\b', text):
        return False
    return configuration_matches(text, vehicle.configuration, profile.dimensions)


def available(video):
    if video.get('status', {}).get('privacyStatus') != 'public':
        return False
    snippet = video.get('snippet', {})
    if not snippet.get('title') or not snippet.get('channelTitle') or snippet.get('liveBroadcastContent') in {'live', 'upcoming'}:
        return False
    region = video.get('contentDetails', {}).get('regionRestriction', {})
    return 'US' not in region.get('blocked', []) and ('allowed' not in region or 'US' in region['allowed'])


def fetch_candidates(client, query, *, max_results=15):
    """One search and batched detail request, retaining provider ordering.

    Caller must reserve quota first. No hidden retries or pagination.
    """
    response = client.get('https://www.googleapis.com/youtube/v3/search', params={
        'key': settings.YOUTUBE_API_KEY, 'part': 'snippet', 'type': 'video', 'q': query,
        'order': 'relevance', 'regionCode': 'US', 'relevanceLanguage': 'en',
        'safeSearch': 'moderate', 'maxResults': max_results,
    })
    response.raise_for_status()
    ids = list(dict.fromkeys(entry['id']['videoId'] for entry in response.json().get('items', [])
                             if entry.get('id', {}).get('videoId')))[:max_results]
    if not ids:
        return []
    response = client.get('https://www.googleapis.com/youtube/v3/videos', params={
        'key': settings.YOUTUBE_API_KEY, 'part': 'snippet,contentDetails,status', 'id': ','.join(ids),
    })
    response.raise_for_status()
    by_id = {v['id']: v for v in response.json().get('items', [])}
    return [by_id[vid] for vid in ids if vid in by_id]


def card(video):
    snippet = video['snippet']
    return dict(id=video['id'], url='https://www.youtube.com/watch?' + urlencode({'v': video['id']}),
                title=snippet['title'], channel=snippet['channelTitle'],
                thumbnail=snippet.get('thumbnails', {}).get('medium', {}).get('url', ''),
                duration=video.get('contentDetails', {}).get('duration', '').removeprefix('PT').lower(),
                label=MATCH_LABEL)


def reserve_search():
    day = timezone.now().astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
    return consume('youtube-search:' + day, settings.YOUTUBE_SEARCH_BUDGET, 172800)


def discover(vehicle, item):
    fallback = search_url(vehicle, item)

    def result(videos=(), outcome='no_matches'):
        return {'videos': list(videos), 'outcome': outcome, 'search_url': fallback, 'notice': NOTICES[outcome]}

    if item.key not in PROFILES:
        return result()
    if not settings.YOUTUBE_API_KEY:
        return result(outcome='unavailable')
    now = timezone.now()
    cached, _ = VideoSearchCache.objects.get_or_create(key=cache_key(vehicle, item))
    if cached.expires_at and cached.expires_at > now:
        return result(**cached.results)
    # Both expiry and lease are atomic: don't repeat a just-completed lookup.
    claimed = (VideoSearchCache.objects.filter(pk=cached.pk)
               .filter(Q(lease_until__isnull=True) | Q(lease_until__lt=now))
               .filter(Q(expires_at__isnull=True) | Q(expires_at__lte=now))
               .update(lease_until=now + timedelta(seconds=90)))
    if not claimed:
        cached.refresh_from_db()
        if cached.expires_at and cached.expires_at > now:
            return result(**cached.results)
        return result(outcome='refreshing')
    started = time.monotonic()
    results, seen = [], set()
    success = True
    candidates_count = 0
    try:
        with httpx.Client(timeout=5.0) as client:
            for query, _ in queries(vehicle, item):
                if not reserve_search():
                    success = False
                    break
                candidates = fetch_candidates(client, query)
                candidates_count += len(candidates)
                for video in candidates:
                    vid = video['id']
                    if vid in seen:
                        continue
                    seen.add(vid)
                    if available(video) and candidate_matches(video, vehicle, item):
                        results.append(card(video))
                    if len(results) == 3:
                        break
                if len(results) == 3:
                    break
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        # Exceptions/HTTP URLs may contain the key; log neither.
        logger.warning('youtube_lookup_failed')
        success = False
    finally:
        outcome = ('matches' if results else 'no_matches') if success else 'unavailable'
        ttl = timedelta(days=7 if results else 1) if success else timedelta(minutes=5)
        finished = timezone.now()
        VideoSearchCache.objects.filter(pk=cached.pk).update(
            results={'videos': results, 'outcome': outcome}, fetched_at=finished,
            expires_at=finished + ttl, lease_until=None)
        logger.info('youtube_lookup outcome=%s candidates=%d accepted=%d elapsed_ms=%d',
                    outcome, candidates_count, len(results), (time.monotonic() - started) * 1000)
    return result(results, outcome)
