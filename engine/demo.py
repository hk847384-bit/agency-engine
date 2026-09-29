"""
BUILD — generate a real one-page website for a lead.

The pitch only works because the thing already exists. "I built you a website,
here it is" beats "I could build you a website" every time, and the whole point
of the Places data is that we already know their name, category, rating,
opening hours and have their own photographs.

Photos come through the Places photo endpoint. We download and inline them as
data URIs so a demo keeps working after the photo reference expires, and so
each demo is a single self-contained file you can host anywhere.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
PHOTO_URL = 'https://places.googleapis.com/v1/{name}/media'

PALETTES = [
    ('#0f3d3e', '#ffffff'), ('#1b3a6b', '#ffffff'), ('#7a2e2e', '#ffffff'),
    ('#2b2d42', '#ffffff'), ('#14532d', '#ffffff'), ('#4a2c6d', '#ffffff'),
    ('#8a4b08', '#ffffff'), ('#0b4f6c', '#ffffff'),
]

COPY = {
    'salon': ('Looking your best takes one appointment.',
              'Cuts, colour and care from people who have been doing this for years — '
              'and who will remember how you like it next time.',
              [('Hair', 'Cuts, styling and colour for every length and texture.'),
               ('Skin & beauty', 'Facials, threading and treatments that actually suit you.'),
               ('Bridal', 'Packages for the day itself and every function around it.')]),
    'clinic': ('Care that starts with being listened to.',
               'Appointments that run on time, clear explanations, and follow-up '
               'that does not leave you guessing.',
               [('Consultations', 'Unhurried appointments with a doctor who explains things.'),
                ('Diagnostics', 'On-site testing so you are not sent across town.'),
                ('Follow-up', 'We check in after treatment, not just during it.')]),
    'restaurant': ('Cooked fresh, served warm.',
                   'A short menu done properly, with the dishes people come back for '
                   'and room for the whole family.',
                   [('Dine in', 'Comfortable seating for families and groups.'),
                    ('Takeaway', 'Call ahead and it will be ready when you are.'),
                    ('Catering', 'Events, functions and office orders at short notice.')]),
    'gym': ('Turn up. We handle the rest.',
            'Proper equipment, coaches who correct your form, and a plan that fits '
            'around the hours you actually have.',
            [('Memberships', 'Monthly and yearly plans with no hidden charges.'),
             ('Personal training', 'One-to-one coaching built around your goals.'),
             ('Classes', 'Group sessions morning and evening, all levels welcome.')]),
    'default': ('{name} — {category} you can rely on.',
                'Straightforward service, fair prices, and the kind of work that gets '
                'recommended to a neighbour.',
                [('Quality work', 'Done properly the first time, by people who take pride in it.'),
                 ('Fair pricing', 'Clear quotes up front. No surprises at the end.'),
                 ('Local and reachable', 'Call us and you get a person, not a queue.')]),
}


def pick_copy(category: str) -> tuple:
    cat = (category or '').lower()
    for key in COPY:
        if key != 'default' and key in cat:
            return COPY[key]
    for key, aliases in (('salon', ('barber', 'spa', 'beauty', 'parlour', 'parlor')),
                         ('clinic', ('dentist', 'doctor', 'hospital', 'medical', 'health')),
                         ('restaurant', ('cafe', 'food', 'bakery', 'kitchen', 'dhaba')),
                         ('gym', ('fitness', 'yoga', 'sports'))):
        if any(a in cat for a in aliases):
            return COPY[key]
    return COPY['default']


class DemoBuilder:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.env = Environment(
            loader=FileSystemLoader(str(ROOT / 'templates')),
            autoescape=select_autoescape(['html']))
        self.env.filters['tojson'] = lambda v: json.dumps(v)

    # ------------------------------------------------------------- photos
    def photo_data_uri(self, ref: str, max_px: int = 1200) -> str | None:
        if not (ref and self.cfg.google_places_key):
            return None
        try:
            r = requests.get(
                PHOTO_URL.format(name=ref),
                params={'maxWidthPx': max_px, 'key': self.cfg.google_places_key,
                        'skipHttpRedirect': 'false'},
                timeout=20, allow_redirects=True)
            if r.status_code != 200 or not r.content:
                return None
            mime = r.headers.get('Content-Type', 'image/jpeg').split(';')[0]
            if not mime.startswith('image/'):
                return None
            if len(r.content) > 900_000:          # keep the page a sane size
                return None
            return f'data:{mime};base64,' + base64.b64encode(r.content).decode()
        except Exception:
            return None

    # -------------------------------------------------------------- build
    def one(self, row) -> dict:
        lead = dict(row)
        name = lead.get('name') or 'Your Business'
        category = (lead.get('category') or 'local business').replace('_', ' ')
        headline_t, subhead, services = pick_copy(category)

        head = headline_t.format(name=name, category=category)
        photos = []
        for ref in (json.loads(lead.get('photos_json') or '[]'))[:5]:
            uri = self.photo_data_uri(ref)
            if uri:
                photos.append(uri)

        seed = sum(ord(c) for c in name)
        brand, brand_ink = PALETTES[seed % len(PALETTES)]

        maps_url = ''
        if lead.get('lat') and lead.get('lng'):
            maps_url = (f"https://www.google.com/maps/search/?api=1&query="
                        f"{lead['lat']},{lead['lng']}")

        html_out = self.env.get_template('demo_site.html.j2').render(
            biz=lead,
            lang='en',
            brand=brand, brand_ink=brand_ink,
            headline=head,
            subhead=subhead,
            services=[{'title': t, 'body': b} for t, b in services],
            services_lede=f'What {name} does, at a glance.',
            photos=photos,
            hours=json.loads(lead.get('hours_json') or '[]'),
            maps_url=maps_url,
            year=datetime.now().year,
            meta_description=(f'{name} — {category}'
                              + (f" in {lead['city']}" if lead.get('city') else '')
                              + '. Call us today.')[:155],
            demo_note=(f'This is a free sample page built for {name} by '
                       f'{self.cfg.agency_name}. Nothing here is live yet and no '
                       f'content has been published anywhere — it is a mock-up to '
                       f'show what the site could look like. Say the word and we '
                       f'will finish it properly, or say no and we will delete it.'),
        )

        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:48] or f"lead-{lead['id']}"
        slug = f"{slug}-{lead['id']}"
        path = Path(self.cfg.demo_dir) / f'{slug}.html'
        path.write_text(html_out, encoding='utf-8')

        url = f"{self.cfg.demo_base_url.rstrip('/')}/{slug}.html"
        self.store.update(lead['id'], demo_path=str(path), demo_url=url, status='demo')
        return {'id': lead['id'], 'name': name, 'path': str(path), 'url': url,
                'photos': len(photos), 'kb': round(len(html_out) / 1024)}

    def run(self, market: str | None = None, limit: int = 50) -> dict:
        rows = self.store.pending('demo', market, limit)
        built = []
        for row in rows:
            try:
                res = self.one(row)
                built.append(res)
                print(f"  built  {res['name'][:42]:<44} {res['photos']} photos  {res['kb']} KB")
            except Exception as e:
                print(f"  failed {row['name'][:42]:<44} {type(e).__name__}: {e}")
        return {'built': len(built), 'demos': built}
