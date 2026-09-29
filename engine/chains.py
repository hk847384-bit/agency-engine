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


# ------------------------------------------------------------- chain by domain
# The strongest chain signal is not the name — it is whose website it is.
# "Embassy Suites by Hilton Austin Arboretum" slips past a name blocklist, but
# its site is hilton.com. A property on the parent's domain cannot buy a
# website from you: the brand owns the web presence and the franchisee has no
# say in it. This is what let 152 Marriott and Hyatt properties score 103.
CHAIN_DOMAINS = {
    # hotels — the worst offenders, because every property gets its own listing
    'hilton.com', 'marriott.com', 'hyatt.com', 'ihg.com', 'wyndhamhotels.com',
    'choicehotels.com', 'bestwestern.com', 'accor.com', 'radissonhotels.com',
    'fourseasons.com', 'omnihotels.com', 'loewshotels.com', 'ritzcarlton.com',
    'hotels.com', 'booking.com', 'expedia.com', 'motel6.com', 'redroof.com',
    'extendedstayamerica.com', 'sonesta.com', 'drury-hotels.com',
    'druryhotels.com', 'staybridge.com', 'embassysuites3.hilton.com',
    # food, retail, services
    'starbucks.com', 'mcdonalds.com', 'subway.com', 'dominos.com',
    'pizzahut.com', 'kfc.com', 'burgerking.com', 'wendys.com', 'tacobell.com',
    'chipotle.com', 'panerabread.com', 'dunkindonuts.com', 'dunkin.com',
    'walgreens.com', 'cvs.com', 'riteaid.com', 'walmart.com', 'target.com',
    'kroger.com', 'safeway.com', 'albertsons.com', 'publix.com', 'costco.com',
    'wholefoodsmarket.com', 'traderjoes.com', 'homedepot.com', 'lowes.com',
    'bestbuy.com', 'autozone.com', 'oreillyauto.com', 'jiffylube.com',
    'planetfitness.com', 'lafitness.com', 'anytimefitness.com', 'ymca.net',
    'supercuts.com', 'greatclips.com', 'massageenvy.com', 'aspendental.com',
    'hrblock.com', 'theupsstore.com', 'fedex.com', '7-eleven.com', '7-11.com',
    'circlek.com', 'enterprise.com', 'hertz.com', 'avis.com', 'uhaul.com',
}


def is_chain_site(url: str | None) -> bool:
    """True when the website belongs to a parent brand, not this location."""
    if not url:
        return False
    m = re.search(r'https?://([^/:?#]+)', url.strip(), re.I)
    host = (m.group(1) if m else url).lower().removeprefix('www.')
    if host in CHAIN_DOMAINS:
        return True
    root = '.'.join(host.split('.')[-2:])
    return root in CHAIN_DOMAINS


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
