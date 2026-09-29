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

import requests

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
                 radius_m: int = 12000) -> int:
        """
        Free OSM fallback. Pulls shops and amenities around a city centre and
        keeps the ones with a phone number, since we need a way to reach them.
        """
        geo = requests.get('https://nominatim.openstreetmap.org/search',
                           params={'q': f'{city}, {market.country}', 'format': 'json',
                                   'limit': 1},
                           headers={'User-Agent': 'agency-engine/1.0'}, timeout=25)
        hits = geo.json() if geo.status_code == 200 else []
        if not hits:
            return 0
        lat, lon = float(hits[0]['lat']), float(hits[0]['lon'])

        selectors = ''.join(
            f'node(around:{radius_m},{lat},{lon})["{k}"~"{v}"];'
            for k, v in [('shop', '.'), ('amenity', 'clinic|dentist|restaurant|cafe|'
                                                    'pharmacy|veterinary|driving_school')]
        )
        q = f'[out:json][timeout:60];({selectors});out body 400;'
        r = requests.post(OVERPASS, data={'data': q}, timeout=90,
                          headers={'User-Agent': 'agency-engine/1.0'})
        if r.status_code != 200:
            return 0

        found = 0
        for el in r.json().get('elements', []):
            t = el.get('tags', {})
            name = t.get('name')
            phone = t.get('phone') or t.get('contact:phone')
            if not name or not phone:
                continue
            rec = {
                'place_id':  f"osm:{el['id']}",
                'source':    'overpass',
                'market':    market.name,
                'city':      city,
                'name':      name,
                'category':  t.get('shop') or t.get('amenity') or '',
                'address':   ', '.join(filter(None, [
                    t.get('addr:street'), t.get('addr:housenumber'), city])),
                'lat':       el.get('lat'),
                'lng':       el.get('lon'),
                'phone':     phone,
                'phone_e164': to_e164(phone, market.country),
                'website':   t.get('website') or t.get('contact:website'),
                'rating':    None,
                'reviews':   None,
                'hours_json': json.dumps([t['opening_hours']] if t.get('opening_hours') else []),
                'photos_json': json.dumps([]),
                'raw_json':  json.dumps(t)[:8000],
            }
            if self.store.upsert_lead(rec):
                found += 1
        return found

    # --------------------------------------------------------------- run
    def run(self, market_name: str, cities: list[str] | None = None,
            categories: list[str] | None = None, per_query: int = 60,
            use_overpass: bool = False, source: str = 'auto') -> dict:
        """
        source: 'auto'      Places when a key exists, otherwise OpenStreetMap
                'places'    Places only (needs a key)
                'osm'       OpenStreetMap only, free, no key, no billing account
        """
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

        total = 0
        for city in cities:
            if use_places:
                for cat in categories:
                    n = self.places(city, cat, market, per_query)
                    total += n
                    print(f'  {city:<18} {cat:<22} +{n}')
            if use_osm:
                n = self.overpass(city, market, categories)
                total += n
                print(f'  {city:<18} {"openstreetmap":<22} +{n}')
        return {'market': market_name, 'new_leads': total,
                'api_calls': self.calls,
                'sources': [s for s, on in (('places', use_places), ('osm', use_osm)) if on]}
