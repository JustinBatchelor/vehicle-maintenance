import hashlib
import logging
from datetime import timedelta
from urllib.parse import urlencode
import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .limits import consume
from .models import VideoSearchCache

logger=logging.getLogger(__name__)
def queries(vehicle, item):
    c=vehicle.configuration
    exact=f"{c.year} {c.make} {c.model} {c.engine} {c.transmission} {c.drivetrain} {item.search_phrase}"
    return [(exact,"Vehicle-specific search · verify fit"),
            (f"{c.make} {c.model} {item.search_phrase}","Broader model search"),
            (item.search_phrase,"General procedure")]

def discover(vehicle,item):
    searches=queries(vehicle,item)
    fallback="https://www.youtube.com/results?"+urlencode({"search_query":searches[0][0]})
    response={"videos":[],"search_url":fallback,"notice":"Search YouTube for tutorials matched to this vehicle and task."}
    if not settings.YOUTUBE_API_KEY: return response
    key=hashlib.sha256(repr(searches).encode()).hexdigest()
    now=timezone.now()
    cached,_=VideoSearchCache.objects.get_or_create(key=key)
    if cached.expires_at and cached.expires_at>now:
        return {**response,"videos":cached.results,"notice":""}
    # Atomic lease avoids concurrent requests spending quota on the same search.
    claimed=VideoSearchCache.objects.filter(pk=cached.pk).filter(Q(lease_until__isnull=True)|Q(lease_until__lt=now)).update(lease_until=now+timedelta(seconds=90))
    if not claimed: return {**response,"notice":"Videos are being refreshed. Try again shortly, or search YouTube."}
    results=[]; seen=set(); success=True
    try:
        with httpx.Client(timeout=5.0) as client:
            for query,label in searches:
                day=now.astimezone(__import__('zoneinfo').ZoneInfo("America/Los_Angeles")).date().isoformat()
                if not consume("youtube-search:"+day,settings.YOUTUBE_SEARCH_BUDGET,172800):
                    success=False;break
                r=client.get("https://www.googleapis.com/youtube/v3/search",params={"key":settings.YOUTUBE_API_KEY,"part":"snippet","type":"video","q":query,"order":"relevance","regionCode":"US","relevanceLanguage":"en","safeSearch":"moderate","maxResults":5})
                r.raise_for_status()
                ids=[entry["id"]["videoId"] for entry in r.json().get("items",[]) if entry.get("id",{}).get("videoId")]
                if not ids: continue
                details=client.get("https://www.googleapis.com/youtube/v3/videos",params={"key":settings.YOUTUBE_API_KEY,"part":"snippet,contentDetails,status","id":",".join(ids)})
                details.raise_for_status()
                by_id={v["id"]:v for v in details.json().get("items",[])}
                for vid in ids:
                    v=by_id.get(vid)
                    if not v or vid in seen or v.get("status",{}).get("privacyStatus")!="public":continue
                    region=v.get("contentDetails",{}).get("regionRestriction",{})
                    if "US" in region.get("blocked",[]) or ("allowed" in region and "US" not in region["allowed"]):continue
                    snippet=v["snippet"]
                    if snippet.get("liveBroadcastContent") in ["live","upcoming"]:continue
                    seen.add(vid)
                    duration=v.get("contentDetails",{}).get("duration","").removeprefix("PT").lower()
                    results.append(dict(id=vid,url="https://www.youtube.com/watch?"+urlencode({"v":vid}),title=snippet["title"],channel=snippet["channelTitle"],thumbnail=snippet.get("thumbnails",{}).get("medium",{}).get("url",""),duration=duration,label=label))
                    if len(results)==3:break
                if len(results)==3:break
    except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
        # Do not log HTTP exceptions: the request URL contains the API key.
        logger.warning("youtube_lookup_failed")
        success=False
    finally:
        ttl=timedelta(days=7 if results else 1) if success else timedelta(minutes=5)
        VideoSearchCache.objects.filter(pk=cached.pk).update(results=results,fetched_at=now,expires_at=now+ttl,lease_until=None)
    return {**response,"videos":results,"notice":"" if success and results else "No video cards are available right now. You can still search YouTube."}
