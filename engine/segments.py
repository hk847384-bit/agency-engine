"""
Segment analysis — which kinds of business are actually worth chasing.

Rather than guessing a category list up front, the finder sweeps every
commercial business it can see and this module works out, from what came back,
which segments deserve your time.

Four things decide that, and only one of them is a judgement call:

  problem rate   measured — what share of this segment has no site, a broken
                 site, or no way to book. A big market is one with a big gap.
  reachability   measured — what share have a phone, and an email we could find
  traction       measured — average reviews, a proxy for "spends on marketing"
  value          the judgement call — an implant dentist and a corner shop both
                 need a website, but only one of them can pay four figures for
                 it. That table is below and you should edit it.
"""

from __future__ import annotations

import math
import re

# ---------------------------------------------------------------- value table
# Roughly: what a website, an SEO retainer or an automation build is worth to
# this kind of business, driven by their customer lifetime value. Edit freely —
# this is the one number in the system that is opinion rather than measurement.

VALUE = {
    # one customer is worth thousands
    3.0: ('dentist', 'orthodont', 'plastic surg', 'cosmetic surg', 'dermatolog',
          'fertility', 'ivf', 'cosmetic clinic', 'aesthetic', 'med spa', 'medspa',
          'lawyer', 'attorney', 'solicitor', 'law firm', 'barrister',
          'estate_agent', 'real estate', 'private school', 'oral surgeon',
          'hair transplant', 'bariatric', 'laser clinic', 'ophthalmolog'),

    # high-value trade or professional services
    2.2: ('chiropract', 'physiotherap', 'osteopath', 'podiatr', 'optician',
          'optometr', 'hearing', 'audiolog', 'veterinary', 'vet_clinic',
          'accountant', 'tax_advisor', 'financial', 'insurance', 'mortgage',
          'architect', 'surveyor', 'roofer', 'hvac', 'plumber', 'electrician',
          'builder', 'contractor', 'glazier', 'car_dealer', 'car repair',
          'wedding', 'events_venue', 'hotel', 'guest_house', 'funeral',
          'driving_school', 'nursing_home', 'childcare', 'kindergarten',
          'fitness_centre', 'sports_centre', 'golf', 'security', 'moving',
          'pest_control', 'solar', 'landscap', 'flooring', 'kitchen', 'interior'),

    # steady local trade, moderate ticket
    1.5: ('hairdresser', 'beauty', 'barber', 'spa', 'nail', 'tattoo', 'massage',
          'photo', 'florist', 'jewelry', 'jeweller', 'furniture', 'bicycle',
          'travel_agency', 'pet_grooming', 'dry_cleaning', 'tailor', 'shoemaker',
          'restaurant', 'cafe', 'bakery', 'butcher', 'deli', 'caterer', 'pub',
          'bar', 'clothes', 'boutique', 'sports', 'garden_centre', 'car_rental',
          'car_wash', 'copyshop', 'printer', 'storage', 'gym', 'yoga', 'dance'),

    # low ticket, hard to sell to
    0.7: ('convenience', 'kiosk', 'newsagent', 'tobacco', 'vacant', 'laundry',
          'fast_food', 'takeaway', 'charity', 'second_hand', 'variety_store',
          'lottery', 'money_lender', 'pawnbroker', 'vending', 'atm',
          'bureau_de_change', 'ice_cream', 'chemist', 'supermarket'),
}

# things that are not businesses you can sell to
EXCLUDE = ('atm', 'bench', 'bicycle_parking', 'post_box', 'toilets', 'shelter',
           'waste_basket', 'recycling', 'drinking_water', 'bus_stop', 'parking',
           'fuel', 'charging_station', 'telephone', 'clock', 'fountain',
           'place_of_worship', 'townhall', 'police', 'fire_station', 'library',
           'public_building', 'community_centre', 'social_facility', 'hospital',
           'university', 'college', 'school', 'bank', 'post_office', 'embassy',
           'courthouse', 'prison', 'marketplace')


def canon(raw: str) -> str:
    """Normalise an OSM tag or a Places display name into one label."""
    c = (raw or '').strip().lower().replace('-', '_')
    c = re.sub(r'\s+', '_', c)
    c = re.sub(r'_(shop|store|clinic|services?|company|centre|center)$', '', c)
    return c or 'unknown'


def value_of(category: str) -> float:
    c = canon(category).replace('_', ' ')
    for weight, keys in sorted(VALUE.items(), reverse=True):
        if any(k.replace('_', ' ') in c for k in keys):
            return weight
    return 1.0                     # unknown segment, treated as average


def is_excluded(category: str) -> bool:
    c = canon(category)
    return any(x == c or x in c for x in EXCLUDE)


# ------------------------------------------------------------------ scorecard
def scorecard(store, market: str | None = None, min_leads: int = 4) -> list[dict]:
    """
    Rank every segment in the database by how good a prospect pool it is.

    opportunity = value x problem-rate x reachability x reach-of-market
    """
    sql = ("SELECT category, offer, website, email, phone_e164, reviews, score "
           "FROM leads WHERE status != 'skip'")
    args: list = []
    if market:
        sql += ' AND market=?'
        args.append(market)
    rows = store.db.execute(sql, args).fetchall()

    buckets: dict[str, dict] = {}
    for r in rows:
        cat = canon(r['category'])
        if not cat or is_excluded(cat):
            continue
        b = buckets.setdefault(cat, {
            'segment': cat, 'leads': 0, 'no_site': 0, 'problem': 0,
            'with_email': 0, 'with_phone': 0, 'reviews_total': 0,
            'reviews_n': 0, 'diagnosed': 0,
            'webdev': 0, 'seo': 0, 'automation': 0, 'other': 0})
        b['leads'] += 1
        if not (r['website'] or '').strip():
            b['no_site'] += 1
        if (r['email'] or '').strip():
            b['with_email'] += 1
        if (r['phone_e164'] or '').strip():
            b['with_phone'] += 1
        if r['reviews']:
            b['reviews_total'] += r['reviews']
            b['reviews_n'] += 1
        offer = (r['offer'] or '').strip()
        if offer:
            b['diagnosed'] += 1
            b[offer] = b.get(offer, 0) + 1
            if offer in ('webdev', 'seo', 'automation'):
                b['problem'] += 1

    out = []
    for b in buckets.values():
        if b['leads'] < min_leads:
            continue
        n = b['leads']
        problem_rate = (b['problem'] / b['diagnosed']) if b['diagnosed'] else 0.5
        reach = (0.65 * (b['with_phone'] / n)) + (0.35 * (b['with_email'] / n))
        avg_reviews = (b['reviews_total'] / b['reviews_n']) if b['reviews_n'] else 0
        traction = min(1.0, math.log1p(avg_reviews) / math.log1p(150)) if avg_reviews else 0.45
        value = value_of(b['segment'])
        volume = math.log1p(n) / math.log1p(200)

        opportunity = 100 * value * problem_rate * (0.25 + 0.75 * reach) \
            * (0.55 + 0.45 * traction) * (0.45 + 0.55 * volume)

        out.append({**b,
                    'value': round(value, 2),
                    'problem_rate': round(problem_rate, 2),
                    'reachability': round(reach, 2),
                    'avg_reviews': round(avg_reviews, 1),
                    'opportunity': round(opportunity, 1)})

    out.sort(key=lambda d: -d['opportunity'])
    return out


def render(rows: list[dict], top: int = 25) -> str:
    if not rows:
        return '\nNo segments yet — run find and diagnose first.\n'
    w = max(len(r['segment']) for r in rows[:top]) + 2
    lines = [
        '',
        f"{'segment':<{w}}{'score':>7}{'leads':>7}{'gap%':>6}{'reach':>7}"
        f"{'value':>7}{'web':>6}{'seo':>5}{'auto':>6}{'email':>7}",
        '-' * (w + 58),
    ]
    for r in rows[:top]:
        lines.append(
            f"{r['segment']:<{w}}{r['opportunity']:>7.1f}{r['leads']:>7}"
            f"{r['problem_rate'] * 100:>5.0f}%{r['reachability']:>7.2f}"
            f"{r['value']:>7.1f}{r['webdev']:>6}{r['seo']:>5}"
            f"{r['automation']:>6}{r['with_email']:>7}")
    lines += [
        '',
        'score = value x problem-rate x reachability x traction x volume',
        'gap%  = share of diagnosed leads with a real problem to sell against',
        'reach = share you can actually contact (phone weighted 65, email 35)',
        '',
    ]
    return '\n'.join(lines)
