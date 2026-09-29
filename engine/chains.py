"""
Chain detection.

A Starbucks is not a lead. It has a marketing department, `press@starbucks.com`
goes to a corporate inbox, and no franchisee can buy a website from you. The
first real run of this engine came back with seven Starbucks at the top of the
list, which is what this file exists to prevent.

Two signals, because neither is enough alone:

  a published blocklist   catches the obvious international names
  repetition in your own  catches regional chains I have never heard of —
  data                    if the same name appears in three cities, it is a chain
"""

from __future__ import annotations

import re

BLOCKLIST = {
    # coffee, food, fast food
    'starbucks', 'dunkin', 'dunkin donuts', 'costa coffee', 'caffe nero',
    'pret a manger', 'mcdonalds', "mcdonald's", 'burger king', 'kfc', 'subway',
    'dominos', "domino's", 'pizza hut', 'papa johns', "papa john's", 'wendys',
    "wendy's", 'taco bell', 'chipotle', 'five guys', 'nandos', "nando's",
    'greggs', 'chick-fil-a', 'popeyes', 'sonic drive-in', 'arbys', "arby's",
    'jimmy johns', "jimmy john's", 'panera bread', 'dairy queen', 'whataburger',
    'in-n-out burger', 'raising canes', "raising cane's", 'jersey mikes',
    'panda express', 'little caesars', 'baskin-robbins', 'krispy kreme',
    'tim hortons', 'peets coffee', "peet's coffee", 'dutch bros',

    # retail, grocery, pharmacy
    'walmart', 'target', 'costco', 'kroger', 'safeway', 'albertsons', 'publix',
    'whole foods market', 'trader joes', "trader joe's", 'aldi', 'lidl',
    'tesco', 'sainsburys', "sainsbury's", 'asda', 'morrisons', 'waitrose',
    'co-op food', 'marks and spencer', 'walgreens', 'cvs pharmacy', 'cvs',
    'rite aid', 'boots', 'superdrug', 'dollar general', 'dollar tree',
    'family dollar', '7-eleven', 'circle k', 'wawa', 'quiktrip', 'sheetz',
    'home depot', 'lowes', "lowe's", 'best buy', 'ikea', 'staples', 'gamestop',
    'autozone', "o'reilly auto parts", 'advance auto parts', 'napa auto parts',
    'petco', 'petsmart', 'tractor supply', 'ace hardware', 'michaels',
    'hobby lobby', 'ross dress for less', 'tj maxx', 'marshalls', 'kohls',
    "kohl's", 'macys', "macy's", 'nordstrom', 'old navy', 'gap', 'h&m', 'zara',
    'uniqlo', 'primark', 'nike', 'adidas', 'foot locker', 'sephora', 'ulta',
    'ulta beauty', 'bath & body works', 'victorias secret', 'lululemon',

    # chain salons, gyms, services
    'supercuts', 'great clips', 'sport clips', 'fantastic sams', 'regis salon',
    'toni&guy', 'drybar', 'european wax center', 'massage envy',
    'planet fitness', 'la fitness', 'anytime fitness', 'orangetheory fitness',
    'f45 training', 'gold gym', "gold's gym", '24 hour fitness', 'crunch fitness',
    'pure gym', 'puregym', 'the gym group', 'snap fitness', 'ymca',
    'jiffy lube', 'valvoline instant oil change', 'midas', 'firestone',
    'discount tire', 'les schwab', 'kwik fit', 'halfords', 'enterprise rent-a-car',
    'hertz', 'avis', 'budget car rental', 'u-haul', 'fedex office', 'ups store',
    'the ups store', 'h&r block', 'jackson hewitt',

    # banks, telecoms, hotels
    'chase bank', 'bank of america', 'wells fargo', 'citibank', 'us bank',
    'pnc bank', 'td bank', 'barclays', 'hsbc', 'natwest', 'lloyds bank',
    'santander', 'halifax', 'verizon', 'at&t store', 't-mobile', 'sprint',
    'vodafone', 'ee', 'three', 'o2', 'xfinity', 'spectrum',
    'holiday inn', 'hampton inn', 'marriott', 'hilton', 'best western',
    'la quinta', 'comfort inn', 'motel 6', 'super 8', 'travelodge',
    'premier inn', 'days inn', 'quality inn', 'residence inn', 'courtyard',

    # dental / medical chains
    'aspen dental', 'western dental', 'smile direct club', 'bright now dental',
    'heartland dental', 'mydentist', 'bupa dental care', '{my}dentist',
    'minuteclinic', 'urgent care', 'concentra', 'lenscrafters', 'pearle vision',
    'visionworks', 'americas best', "america's best", 'specsavers', 'vision express',
    'banfield pet hospital', 'vca animal hospital',
}

# e.g. "Starbucks #1234", "Subway (Downtown)", "Costa Coffee - Airport"
SUFFIX = re.compile(r'\s*(#\d+|\(\s*[^)]{1,40}\s*\)|[-–—]\s*[\w\s]{1,30})$')


def normalise(name: str) -> str:
    n = (name or '').strip().lower()
    n = SUFFIX.sub('', n)
    n = re.sub(r'[^a-z0-9& ]+', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def is_blocklisted(name: str) -> bool:
    n = normalise(name)
    if not n:
        return False
    if n in BLOCKLIST:
        return True
    # "starbucks coffee", "the ups store austin"
    return any(n.startswith(b + ' ') or n == b for b in BLOCKLIST)


def find_repeats(names: list[str], threshold: int = 3) -> set[str]:
    """Names that show up `threshold`+ times are a chain, whoever they are."""
    counts: dict[str, int] = {}
    for nm in names:
        n = normalise(nm)
        if n:
            counts[n] = counts.get(n, 0) + 1
    return {n for n, c in counts.items() if c >= threshold}
