"""Reproducible live comparison. Never writes application caches or garage data.

Use --cluster to keep the key in the existing web pod and reserve searches against
its shared daily counter. Only public configuration/task queries leave the app.
Artifacts contain expiring YouTube metadata: keep them outside the checkout.
Human labels are independent of the matcher; unreviewed is never a passing grade.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
# Keep the original 40-case comparison stable when the maintenance catalog grows.
BENCHMARK_CONFIGURATIONS = (
    'ford-f150-2010-4x2', 'ford-f150-2010-4x4', 'nissan-altima-2012-cvt',
    'nissan-altima-2012-manual-coupe', 'subaru-crosstrek-2021-limited',
)
# This short process uses the already-deployed key and limiter, not new app code.
# No key or API URL is returned, even on provider failures.
REMOTE_FETCH = '''
import os, sys, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo
from garage.limits import consume
import httpx
query = json.load(sys.stdin)
day = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
if not settings.YOUTUBE_API_KEY:
    print(json.dumps({"error": "missing_key"})); sys.exit(0)
if not consume("youtube-search:" + day, settings.YOUTUBE_SEARCH_BUDGET, 172800):
    print(json.dumps({"error": "daily_budget"})); sys.exit(0)
try:
    with httpx.Client(timeout=5.0) as client:
        params = {"key": settings.YOUTUBE_API_KEY, "part": "snippet", "type": "video", "q": query["query"], "maxResults": query["max_results"], "order": "relevance", "regionCode": "US", "relevanceLanguage": "en", "safeSearch": "moderate"}
        r = client.get("https://www.googleapis.com/youtube/v3/search", params=params)
        r.raise_for_status()
        ids = list(dict.fromkeys(v["id"]["videoId"] for v in r.json().get("items", []) if v.get("id", {}).get("videoId")))
        results = []
        if ids:
            r = client.get("https://www.googleapis.com/youtube/v3/videos", params={"key": settings.YOUTUBE_API_KEY, "part": "snippet,contentDetails,status", "id": ",".join(ids)})
            r.raise_for_status()
            by_id = {v["id"]: v for v in r.json().get("items", [])}
            results = [by_id[i] for i in ids if i in by_id]
        print(json.dumps({"videos": results}))
except Exception:
    print(json.dumps({"error": "provider_unavailable"}))
'''


def cases():
    catalog = json.loads((ROOT / 'data/schedules.json').read_text())
    items = {i['key']: SimpleNamespace(**i) for i in catalog['items']}
    configs = {c['key']: SimpleNamespace(**c) for c in catalog['configurations']}
    result = []
    for key in BENCHMARK_CONFIGURATIONS:
        c = configs[key]
        transmission_item = 'at-fluid' if '6R80' in c.transmission else 'mt-replace' if 'manual' in c.transmission else 'cvt-replace'
        for index, key in enumerate(['oil', 'air', 'plugs', 'brakes', 'coolant', transmission_item]):
            result.append((c, items[key], 'dev' if index < 4 else 'holdout'))
    for config, keys in [
        ('ford-f150-2010-4x4', ['front-diff', 'rear-diff', 'air-check']),
        ('nissan-altima-2012-cvt', ['cabin', 'cabin-check', 'cvt']),
        ('subaru-crosstrek-2021-limited', ['cabin', 'brake-fluid-check', 'diff', 'diff-replace']),
    ]:
        result.extend((configs[config], items[key], 'targeted') for key in keys)
    return result


def baseline_queries(c, item):
    return [f'{c.year} {c.make} {c.model} {c.engine} {c.transmission} {c.drivetrain} {item.search_phrase}',
            f'{c.make} {c.model} {item.search_phrase}', item.search_phrase]


def metrics(rows, method):
    completed = [r for r in rows if r.get(method, {}).get('complete')]
    displayed = [v for r in completed for v in r[method]['videos']]
    counts = Counter(v.get('review', 'unreviewed') for v in displayed)
    known = [r for r in completed if r.get('known_available') is True]
    covered = sum(any(v.get('review') == 'relevant' for v in r[method]['videos']) for r in known)
    precision = counts['relevant'] / len(displayed) if displayed and not counts['unreviewed'] else None
    coverage = covered / len(known) if known else None
    all_reviewed = all(v.get('review') in {'relevant', 'irrelevant', 'uncertain'}
                       and isinstance(v.get('contradiction'), bool) and v.get('review_notes') for v in displayed)
    contradictions = sum(v.get('contradiction') is True for v in displayed)
    complete = len(completed) == len(rows) and bool(rows)
    ground_truth_complete = all(isinstance(r.get('known_available'), bool) and r.get('availability_notes') for r in rows)
    return {'cases': len(rows), 'completed': len(completed), 'displayed': len(displayed),
            'reviews': dict(counts), 'precision': precision, 'known_available_cases': len(known),
            'coverage': coverage, 'contradictions': contradictions,
            'empty_rate': sum(not r[method]['videos'] for r in completed) / len(completed) if completed else None,
            'release_gate': bool(complete and ground_truth_complete and all_reviewed and precision is not None
                                 and precision >= .9 and coverage is not None and coverage >= .8 and contradictions == 0)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Explicitly allow provider calls')
    parser.add_argument('--cluster', action='store_true', help='Use deployed credential and shared search limiter')
    parser.add_argument('--split', choices=['dev', 'holdout', 'targeted', 'all'], default='dev')
    parser.add_argument('--max-searches', type=int, default=20)
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    path = args.artifact.resolve()
    if path.is_relative_to(ROOT):
        parser.error('Store provider metadata outside the repository')
    if args.max_searches < 0 or args.max_searches > 80:
        parser.error('--max-searches must be between 0 and 80')
    now = datetime.now(timezone.utc)
    if path.exists():
        artifact = json.loads(path.read_text())
        if now >= datetime.fromisoformat(artifact['expires_at']):
            path.unlink()
            parser.error('Expired metadata deleted; start a fresh evaluation')
    else:
        artifact = {'created_at': now.isoformat(), 'expires_at': (now+timedelta(days=29)).isoformat(),
                    'requests': {}, 'cases': {}}
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from garage.videos import queries, candidate_matches, available, fetch_candidates, reserve_search, cache_key
    import httpx
    from django.conf import settings

    used = 0
    def save():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact, indent=2)+'\n')
        path.chmod(0o600)

    def fetch(query, max_results):
        nonlocal used
        key = hashlib.sha256(repr((query, max_results)).encode()).hexdigest()
        if key in artifact['requests']:
            return artifact['requests'][key]
        if not args.live or used >= args.max_searches:
            raise RuntimeError('run_budget_or_offline')
        used += 1
        if args.cluster:
            proc = subprocess.run(['oc', '-n', 'vehicle-maintenance', 'exec', '-i', 'deploy/garage-web', '--', 'python', '-c', REMOTE_FETCH],
                                  input=json.dumps({'query': query, 'max_results': max_results}), text=True, capture_output=True, timeout=45)
            if proc.returncode:
                raise RuntimeError('cluster_unavailable')
            data = json.loads(proc.stdout)
            if 'error' in data:
                raise RuntimeError(data['error'])
            values = data['videos']
        else:
            if not settings.YOUTUBE_API_KEY:
                raise RuntimeError('missing_key')
            if not reserve_search():
                raise RuntimeError('daily_budget')
            with httpx.Client(timeout=5.0) as client:
                values = fetch_candidates(client, query, max_results=max_results)
        artifact['requests'][key] = values
        save()
        return values

    for c, item, split in cases():
        case_id = c.key + ':' + item.key
        row = artifact['cases'].setdefault(case_id, {'configuration': c.key, 'item': item.key, 'split': split,
                                                    'known_available': None, 'availability_notes': ''})
        if args.report or (args.split != 'all' and split != args.split):
            continue
        vehicle = SimpleNamespace(configuration=c)
        for method in ['baseline', 'proposed']:
            fingerprint = 'original-v1' if method == 'baseline' else cache_key(vehicle, item)
            previous = row.get(method, {})
            if previous.get('complete') and previous.get('fingerprint') == fingerprint:
                continue
            selected, seen = [], set()
            searches = baseline_queries(c, item) if method == 'baseline' else [q for q, _ in queries(vehicle, item)]
            error = None
            try:
                for query in searches:
                    for candidate in fetch(query, 5 if method == 'baseline' else 15):
                        if candidate['id'] in seen or not available(candidate):
                            continue
                        seen.add(candidate['id'])
                        if method == 'proposed' and not candidate_matches(candidate, vehicle, item):
                            continue
                        old_review = next((v for v in previous.get('videos', []) if v['id'] == candidate['id']), {})
                        selected.append({'id': candidate['id'], 'title': candidate['snippet']['title'],
                                         'review': old_review.get('review', 'unreviewed'),
                                         'contradiction': old_review.get('contradiction'),
                                         'review_notes': old_review.get('review_notes', '')})
                        if len(selected) == 3:
                            break
                    if len(selected) == 3:
                        break
            except (RuntimeError, httpx.HTTPError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
                # Never stringify provider exceptions: API URLs contain credentials.
                known_errors = {'run_budget_or_offline', 'cluster_unavailable', 'missing_key', 'daily_budget', 'provider_unavailable'}
                error = exc.args[0] if isinstance(exc, RuntimeError) and exc.args and exc.args[0] in known_errors else 'provider_or_access_failure'
            row[method] = {'fingerprint': fingerprint, 'complete': error is None, 'error': error, 'videos': selected}
            save()
            print(f'{case_id} {method}: {len(selected)} cards; {"incomplete" if error else "complete"}', flush=True)
    save()
    summary = {split: {method: metrics([r for r in artifact['cases'].values() if r['split'] == split], method)
                       for method in ['baseline', 'proposed']} for split in ['dev', 'holdout', 'targeted']}
    print(json.dumps({'search_attempts_this_run': used, 'summary': summary}, indent=2))


if __name__ == '__main__':
    main()
