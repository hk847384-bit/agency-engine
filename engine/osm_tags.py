"""
Mapping from the plain-English categories in config.yaml to OpenStreetMap tags.

OSM does not have a "cosmetic dentist" tag. It has `amenity=dentist` and
`healthcare=dentist`, and the cosmetic part lives in the name. So each category
maps to a set of tag selectors, and optionally a name pattern to narrow it.

Without this the Overpass query falls back to "every shop in the city", which
is how a search for med spas in Austin comes back full of Starbucks.
"""

from __future__ import annotations

import re

# category keyword -> (list of (key, value-regex), optional name regex)
TAGS: dict[str, tuple[list[tuple[str, str]], str | None]] = {
    'dentist':        ([('amenity', 'dentist'), ('healthcare', 'dentist')], None),
    'cosmetic dentist': ([('amenity', 'dentist'), ('healthcare', 'dentist')],
                         r'cosmetic|smile|aesthetic|implant|veneer'),
    'orthodontist':   ([('healthcare', 'orthodontist'), ('amenity', 'dentist')],
                       r'orthodont|braces|align'),
    'med spa':        ([('shop', 'beauty'), ('amenity', 'clinic'),
                        ('healthcare', 'clinic|centre|center')],
                       r'med\s?spa|medspa|aesthetic|laser|botox|skin|rejuven'),
    'aesthetic':      ([('shop', 'beauty'), ('amenity', 'clinic')],
                       r'aesthetic|skin|laser|botox|cosmetic'),
    'plastic surgeon': ([('healthcare', 'doctor|clinic'), ('amenity', 'clinic|doctors')],
                        r'plastic|cosmetic surg|surgeon'),
    'chiropractor':   ([('healthcare', 'chiropractor'), ('amenity', 'clinic|doctors')],
                       r'chiro'),
    'physiotherapy':  ([('healthcare', 'physiotherapist'), ('amenity', 'clinic')],
                       r'physio|sports (injury|therapy)|rehab'),
    'clinic':         ([('amenity', 'clinic|doctors'), ('healthcare', 'clinic|doctor')], None),
    'veterinary':     ([('amenity', 'veterinary'), ('healthcare', 'veterinary')], None),
    'pharmacy':       ([('amenity', 'pharmacy'), ('healthcare', 'pharmacy')], None),

    'lawyer':         ([('office', 'lawyer')], None),
    'attorney':       ([('office', 'lawyer')], None),
    'solicitor':      ([('office', 'lawyer')], None),
    'law firm':       ([('office', 'lawyer')], None),
    'personal injury': ([('office', 'lawyer')], r'injur|accident|compensation'),
    'family law':     ([('office', 'lawyer')], r'family|divorce|matrimonial'),
    'accountant':     ([('office', 'accountant|tax_advisor|financial')], None),

    'real estate':    ([('office', 'estate_agent')], None),
    'estate agent':   ([('office', 'estate_agent')], None),

    'roofing':        ([('craft', 'roofer'), ('shop', 'trade|doityourself')], r'roof'),
    'hvac':           ([('craft', 'hvac|plumber'), ('shop', 'trade')],
                       r'hvac|heating|air.?condition|cooling'),
    'plumber':        ([('craft', 'plumber')], None),
    'electrician':    ([('craft', 'electrician')], None),
    'landscap':       ([('craft', 'gardener'), ('shop', 'garden_centre'),
                        ('landuse', 'plant_nursery')], r'landscap|lawn|garden'),
    'interior design': ([('shop', 'interior_decoration'), ('office', 'architect')],
                        r'interior|design'),

    'salon':          ([('shop', 'hairdresser|beauty')], None),
    'beauty':         ([('shop', 'beauty|hairdresser')], None),
    'barber':         ([('shop', 'hairdresser')], r'barber'),
    'spa':            ([('leisure', 'spa'), ('shop', 'beauty')], None),

    'gym':            ([('leisure', 'fitness_centre|sports_centre')], None),
    'fitness':        ([('leisure', 'fitness_centre|sports_centre')], None),

    'restaurant':     ([('amenity', 'restaurant')], None),
    'cafe':           ([('amenity', 'cafe')], None),
    'hotel':          ([('tourism', 'hotel|guest_house')], None),
    'wedding venue':  ([('amenity', 'events_venue'), ('tourism', 'hotel')],
                       r'wedding|banquet|manor|hall'),

    'driving school': ([('amenity', 'driving_school')], None),
    'travel':         ([('shop', 'travel_agency')], None),
    'car rental':     ([('amenity', 'car_rental'), ('shop', 'car')], None),
    'photographer':   ([('shop', 'photo'), ('craft', 'photographer')], None),
    'boutique':       ([('shop', 'clothes|boutique')], None),
}


def plan(categories: list[str]) -> list[tuple[list[tuple[str, str]], re.Pattern | None]]:
    """
    Group the configured categories into Overpass queries.

    Categories with no name filter share one query. Categories that DO need a
    name filter get their own, because a filter is only valid against the tags
    it was written for — applying the roofing pattern to a dentist search would
    throw away every dentist.
    """
    plain: list[tuple[str, str]] = []
    scoped: list[tuple[list[tuple[str, str]], re.Pattern]] = []

    for cat in categories:
        c = (cat or '').lower()
        # longest key first, so "cosmetic dentist" beats "dentist"
        for key in sorted(TAGS, key=len, reverse=True):
            if key in c:
                tags, name_re = TAGS[key]
                if name_re:
                    scoped.append((tags, re.compile(name_re, re.I)))
                else:
                    plain.extend(tags)
                break

    seen, uniq = set(), []
    for t in plain:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    out: list[tuple[list[tuple[str, str]], re.Pattern | None]] = []
    if uniq:
        out.append((uniq, None))
    out.extend(scoped)
    return out


def selectors_for(categories: list[str]):
    """Kept for compatibility: every selector, no name filtering."""
    sels = []
    for tags, _ in plan(categories):
        sels.extend(tags)
    return sels, []


# ------------------------------------------------------- sweep-everything mode
# Every commercial point of interest OSM knows about. Used when you would
# rather collect the whole town and let the segment scorecard tell you which
# parts of it are worth working.

BROAD: list[tuple[str, str]] = [
    ('shop',       '.+'),
    ('office',     '.+'),
    ('craft',      '.+'),
    ('healthcare', '.+'),
    ('amenity',    'restaurant|cafe|bar|pub|fast_food|food_court|ice_cream|'
                   'dentist|doctors|clinic|veterinary|pharmacy|nursing_home|'
                   'childcare|kindergarten|driving_school|language_school|'
                   'music_school|car_rental|car_wash|car_repair|fuel|'
                   'events_venue|conference_centre|nightclub|casino|'
                   'funeral_directors|studio|spa|internet_cafe|coworking_space'),
    ('leisure',    'fitness_centre|sports_centre|spa|golf_course|dance|'
                   'horse_riding|swimming_pool|bowling_alley|escape_game'),
    ('tourism',    'hotel|guest_house|motel|hostel|apartment|chalet'),
]


def plan_all() -> list[tuple[list[tuple[str, str]], None]]:
    """One query per tag key, so no single request times out on Overpass."""
    return [([sel], None) for sel in BROAD]
