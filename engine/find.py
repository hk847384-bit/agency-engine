"""
FIND — source local businesses.

Two sources, deliberately:

  Google Places API   licensed, reliable, and it returns the photos, hours and
                      ratings the demo builder needs. Costs money per request.
  OpenStreetMap       free and open (ODbL). Weaker coverage, but OSM records
                      often have no `website` tag at all, which is exactly the
                      segment we sell web development to.

We never scrape Google Maps HTML. That breaks their terms, gets the IP blocked,
and the API gives richer data anyway.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date

import requests

from . import chains, segments
from .osm_tags import plan as osm_plan, plan_all as osm_plan_all

PLACES_SEARCH = 'https://places.googleapis.com/v1/places:searchText'
OVERPASS = 'https://overpass-api.de/api/interpreter'

FIELDS = ','.join(
    'places.' + f for f in (
        'id', 'displayName', 'formattedAddress', 'location', 'primaryType',
        'primaryTypeDisplayName', 'nationalPhoneNumber', 'internationalPhoneNumber',
        'websiteUri', 'rating', 'userRatingCount', 'regularOpeningHours',
        'photos', 'businessStatus',
    ))


def to_e164(raw: str | None, country: str) -> str:
    """Best-effort E.164. Good enough for dedupe and wa.me links."""
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    cc = {'PK': '92', 'IN': '91', 'US': '1', 'GB': '44', 'AE': '971',
          'SA': '966', 'CA': '1', 'AU': '61'}.get(country.upper(), '')
    if raw.strip().startswith('+'):
        return '+' + digits
    if cc and digits.startswith(cc):
        return '+' + digits
    digits = digits.lstrip('0')
    return f'+{cc}{digits}' if cc else digits


# ------------------------------------------------------------------ category
# OSM lets a mapper write `office=yes` or `shop=yes` when they know a business
# is there but not what kind. Taken literally that produces a segment called
# "yes" — 82 of them turned up in the first full sweep. Treat those as unset
# and keep looking.

GENERIC = {'yes', 'no', 'true', 'unknown', '', 'commercial', 'retail'}

# a last resort, read off the business's own name
NAME_HINTS = [
    # prefixes, not whole words — "Roofing" must match "roof"
    (r'\b(dental|dentist|orthodont|endodont|periodont)',  'dentist'),
    (r'\b(law offices?|law firm|law group|legal|solicitor|attorney|advocates?)',
                                                          'lawyer'),
    (r'\b(account|bookkeep|cpa\b|tax (service|advis|prep))', 'accountant'),
    (r'\b(realty|real estate|estate agent|properties|property group)',
                                                          'estate_agent'),
    (r'\b(insur|assurance)',                              'insurance'),
    (r'\b(roof)',                                         'roofer'),
    (r'\b(plumb)',                                        'plumber'),
    (r'\b(electric)',                                     'electrician'),
    (r'\b(hvac|heating|air.?condition|cooling)',          'hvac'),
    (r'\b(chiropract)',                                   'chiropractor'),
    (r'\b(physio|physical therapy|rehab)',                'physiotherapy'),
    (r'\b(veterinar|animal hospital|vet clinic)',         'veterinary'),
    (r'\b(salon|barber|hair studio|hairdress)',           'hairdresser'),
    (r'\b(med.?spa|aesthetic|laser|botox|skin (clinic|care))', 'beauty'),
    (r'\b(construct|builder|contracting|remodel|renovat)', 'contractor'),
    (r'\b(landscap|lawn care|garden design)',             'landscaping'),
    (r'\b(clinic|medical cent|health cent|physician)',    'clinic'),
    (r'\b(marketing|advertis|consult|media group|digital agency)', 'agency'),
]
NAME_HINTS = [(re.compile(p, re.I), label) for p, label in NAME_HINTS]

# in priority order — the most specific tag that carries a real value wins
CATEGORY_KEYS = ('healthcare:speciality', 'healthcare', 'craft', 'shop',
                 'office', 'amenity', 'leisure', 'tourism', 'club')


def pick_category(tags: dict) -> str:
    """The most specific thing OSM will tell us about what this business does."""
    for key in CATEGORY_KEYS:
        v = (tags.get(key) or '').strip().lower()
        if v and v not in GENERIC:
            return v.split(';')[0]

    # every tag was `yes` — try the name
    name = tags.get('name') or ''
    for pattern, label in NAME_HINTS:
        if pattern.search(name):
            return label

    # still nothing: at least say which kind of tag it was, not "yes"
    for key in CATEGORY_KEYS:
        if (tags.get(key) or '').strip().lower() in GENERIC and tags.get(key):
            return f'{key}_unspecified'
    return 'unknown'


class Finder:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.calls = 0

    # ------------------------------------------------------------- Places
    def places(self, city: str, category: str, market, limit: int = 60) -> int:
        """Text search, paged. Returns how many new leads were stored."""
        if not self.cfg.google_places_key:
            raise RuntimeError('google_places_key is not set')

        found, token = 0, None
        while found < limit and self.calls < self.cfg.limits.places_requests_per_run:
            body = {'textQuery': f'{category} in {city}', 'maxResultCount': 20,
                    'languageCode': market.language}
            if token:
                body['pageToken'] = token
            r = requests.post(
                PLACES_SEARCH, json=body, timeout=25,
                headers={'X-Goog-Api-Key': self.cfg.google_places_key,
                         'X-Goog-FieldMask': FIELDS + ',nextPageToken',
                         'Content-Type': 'application/json'})
            self.calls += 1
            if r.status_code != 200:
                print(f'  places {r.status_code}: {r.text[:200]}')
                break

            data = r.json()
            for p in data.get('places', []):
                if p.get('businessStatus') not in (None, 'OPERATIONAL'):
                    continue
                if self.store.is_suppressed(place_id=p.get('id')):
                    continue
                phone = p.get('nationalPhoneNumber') or p.get('internationalPhoneNumber')
                rec = {
                    'place_id':  p.get('id'),
                    'source':    'places',
                    'market':    market.name,
                    'city':      city,
                    'name':      (p.get('displayName') or {}).get('text', ''),
                    'category':  (p.get('primaryTypeDisplayName') or {}).get('text')
                                 or p.get('primaryType') or category,
                    'address':   p.get('formattedAddress'),
                    'lat':       (p.get('location') or {}).get('latitude'),
                    'lng':       (p.get('location') or {}).get('longitude'),
                    'phone':     phone,
                    'phone_e164': to_e164(p.get('internationalPhoneNumber') or phone,
                                          market.country),
                    'website':   p.get('websiteUri'),
                    'rating':    p.get('rating'),
                    'reviews':   p.get('userRatingCount'),
                    'hours_json': json.dumps(
                        (p.get('regularOpeningHours') or {}).get('weekdayDescriptions', [])),
                    'photos_json': json.dumps(
                        [ph.get('name') for ph in (p.get('photos') or [])][:6]),
                    'raw_json':  json.dumps(p)[:20000],
                }
                if rec['name'] and self.store.upsert_lead(rec):
                    found += 1

            token = data.get('nextPageToken')
            if not token:
                break
            time.sleep(2)          # the page token needs a moment to become valid
        return found

    # ----------------------------------------------------------- Overpass
    def overpass(self, city: str, market, categories: list[str],
                 radius_m: int = 15000, sweep_all: bool = False) -> int:
        """
        Free OSM source, restricted to the categories in config.yaml.

        Without the tag mapping this used to pull every shop in the city, which
        is how a search for med spas came back full of coffee chains.
        """
        queries = osm_plan_all() if sweep_all else osm_plan(categories)
        if not queries:
            print(f'    (no OSM tag mapping for these categories — skipping)')
            return 0

        geo = requests.get('https://nominatim.openstreetmap.org/search',
                           params={'q': f'{city}, {market.country}', 'format': 'json',
                                   'limit': 1},
                           headers={'User-Agent': 'agency-engine/1.0'}, timeout=25)
        hits = geo.json() if geo.status_code == 200 else []
        if not hits:
            return 0
        lat, lon = float(hits[0]['lat']), float(hits[0]['lon'])

        elements: list[dict] = []
        for selectors, name_re in queries:
            parts = []
            for k, v in selectors:
                for kind in ('node', 'way'):
                    parts.append(f'{kind}(around:{radius_m},{lat},{lon})["{k}"~"^({v})$"];')
            q = f'[out:json][timeout:90];({"".join(parts)});out center tags 600;'
            try:
                r = requests.post(OVERPASS, data={'data': q}, timeout=120,
                                  headers={'User-Agent': 'agency-engine/1.0'})
            except Exception as e:
                print(f'    overpass error: {type(e).__name__}')
                continue
            if r.status_code != 200:
                print(f'    overpass {r.status_code}')
                time.sleep(5)
                continue
            for el in r.json().get('elements', []):
                nm = el.get('tags', {}).get('name')
                if not nm:
                    continue
                if name_re and not name_re.search(nm):
                    continue
                elements.append(el)
            time.sleep(2)          # Overpass is free; do not hammer it

        found = skipped_chain = skipped_nophone = 0
        for el in elements:
            t = el.get('tags', {})
            name = t.get('name')
            phone = (t.get('phone') or t.get('contact:phone')
                     or t.get('contact:mobile'))
            if not name:
                continue
            if chains.is_blocklisted(name):
                skipped_chain += 1
                continue
            cat_raw = pick_category(t)
            if segments.is_excluded(cat_raw):
                continue
            if not phone:
                skipped_nophone += 1
                continue

            centre = el.get('center') or {}
            rec = {
                'place_id':  f"osm:{el.get('type','node')[0]}{el['id']}",
                'source':    'overpass',
                'market':    market.name,
                'city':      city,
                'name':      name,
                'category':  cat_raw,
                'address':   ', '.join(filter(None, [
                    t.get('addr:housenumber'), t.get('addr:street'), city])),
                'lat':       el.get('lat') or centre.get('lat'),
                'lng':       el.get('lon') or centre.get('lon'),
                'phone':     phone,
                'phone_e164': to_e164(phone, market.country),
                'website':   (t.get('website') or t.get('contact:website')
                              or t.get('url')),
                'rating':    None,
                'reviews':   None,
                'hours_json': json.dumps([t['opening_hours']] if t.get('opening_hours') else []),
                'photos_json': json.dumps([]),
                'raw_json':  json.dumps(t)[:8000],
            }
            if self.store.upsert_lead(rec):
                found += 1

        if skipped_chain or skipped_nophone:
            print(f'    (skipped {skipped_chain} chains, '
                  f'{skipped_nophone} with no phone)')
        return found

    def prune_chains(self, threshold: int = 3) -> int:
        """
        Suppress any name that turns up `threshold`+ times across the database.

        The blocklist catches Starbucks. This catches the regional chain with
        eleven branches that neither of us has heard of.
        """
        rows = self.store.db.execute(
            "SELECT id, name, place_id FROM leads WHERE status != 'skip'").fetchall()
        repeats = chains.find_repeats([r['name'] for r in rows], threshold)
        if not repeats:
            return 0
        n = 0
        for r in rows:
            if chains.normalise(r['name']) in repeats:
                self.store.update(r['id'], status='skip',
                                  audit_notes='chain: repeated name')
                self.store.suppress('place_id', r['place_id'], 'chain')
                n += 1
        print(f'  pruned {n} leads across {len(repeats)} chains')
        return n

    # --------------------------------------------------------------- run
    def run(self, market_name: str, cities: list[str] | None = None,
            categories: list[str] | None = None, per_query: int = 60,
            use_overpass: bool = False, source: str = 'auto',
            all_categories: bool = False, budget_s: int = 0) -> dict:
        """
        source: 'auto'      Places when a key exists, otherwise OpenStreetMap
                'places'    Places only (needs a key)
                'osm'       OpenStreetMap only, free, no key, no billing account

        budget_s: stop starting new cities once this many seconds have gone.
                  A full sweep of six cities is far more than a CI job's time
                  limit, so it runs a few cities per day and picks up where it
                  left off — the database is the memory.
        """
        started = time.time()
        market = self.cfg.market(market_name)
        cities = cities or market.cities
        categories = categories or market.categories

        has_key = bool(self.cfg.google_places_key)
        if source == 'places' and not has_key:
            raise RuntimeError(
                'google_places_key is not set. Either set GOOGLE_PLACES_KEY, '
                'or run with --source osm to use free OpenStreetMap data.')
        use_places = source in ('places', 'auto') and has_key
        use_osm = use_overpass or source == 'osm' or (source == 'auto' and not has_key)

        if not use_places and use_osm:
            print('  (no Places key — using OpenStreetMap, which is free but '
                  'has no ratings or photos)')

        # rotate the starting city each day, so a budget that only reaches
        # three cities does not mean the last three are never swept
        if budget_s and len(cities) > 1:
            offset = date.today().toordinal() % len(cities)
            cities = cities[offset:] + cities[:offset]

        total = 0
        for city in cities:
            if budget_s and (time.time() - started) > budget_s:
                print(f'  time budget reached — {city} and any after it '
                      f'will be swept on the next run')
                break
            if use_places:
                for cat in categories:
                    n = self.places(city, cat, market, per_query)
                    total += n
                    print(f'  {city:<18} {cat:<22} +{n}')
            if use_osm:
                n = self.overpass(city, market, categories,
                                  sweep_all=all_categories)
                total += n
                print(f'  {city:<18} {"openstreetmap":<22} +{n}')
        return {'market': market_name, 'new_leads': total,
                'api_calls': self.calls,
                'sources': [s for s, on in (('places', use_places), ('osm', use_osm)) if on]}
