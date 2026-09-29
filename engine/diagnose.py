"""
DIAGNOSE — work out what is actually wrong with each business, then route it.

This is the part the reel's system doesn't have. It only asks "is there a
website, yes or no". We sell four things, so we have to tell the difference
between a business with no site, one with a site that no one can find, and one
whose site is fine but who is still answering every booking by hand.

Routing:
    webdev      no site at all, or a "site" that is really a Facebook page,
                or a domain that is parked, dead or unusable on a phone
    seo         a real site that is slow, thin, or missing the basics that
                make it rankable
    automation  a decent site, but nothing on it books, quotes or answers —
                and the category is one where that costs them money daily
    other       a solid site with the basics covered; worth a softer pitch
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .store import now
from .segments import value_of

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

SOCIAL_HOSTS = ('facebook.com', 'fb.me', 'instagram.com', 'linktr.ee',
                'wa.me', 'business.site', 'linkedin.com', 'twitter.com',
                'x.com', 'youtube.com', 'tiktok.com')

PARKED_MARKERS = ('domain is for sale', 'buy this domain', 'parked free',
                  'godaddy.com/forsale', 'this domain may be for sale',
                  'under construction', 'coming soon', 'default web page',
                  'welcome to nginx', 'apache2 ubuntu default page')

# Booking vendors we look for in links and script sources. Matching the bare
# word "appointment" anywhere in the page gives false positives on body copy,
# so intent has to show up in an href, a script src, or actual link text.
BOOKING_HOSTS = ('calendly.com', 'setmore.com', 'acuityscheduling.com',
                 'simplybook.', 'fresha.com', 'zocdoc.com', 'opentable.',
                 'resy.com', 'square.site/book', 'booksy.com', 'timely.',
                 'cal.com', 'youcanbook.me', 'appointlet.com', 'doctolib.',
                 'practo.com', 'zenoti.com', 'mindbodyonline.com')
BOOKING_TEXT = re.compile(
    r'\b(book (now|online|a (table|room|visit)|an appointment)|'
    r'make an appointment|request an appointment|schedule (a|an) '
    r'(visit|appointment|consultation)|reserve a table|book appointment)\b', re.I)
CHAT = ('tawk.to', 'crisp.chat', 'intercom', 'drift.com', 'livechatinc',
        'zendesk', 'freshchat', 'tidio', 'chatbot', 'messenger/plugin')
WHATSAPP = ('wa.me', 'api.whatsapp.com', 'whatsapp://')

# categories where a missed enquiry is money on the floor today
HIGH_INTENT = ('clinic', 'dentist', 'doctor', 'hospital', 'salon', 'spa',
               'barber', 'restaurant', 'cafe', 'hotel', 'gym', 'fitness',
               'real estate', 'lawyer', 'attorney', 'school', 'academy',
               'travel', 'tour', 'car', 'repair', 'plumber', 'electrician',
               'photographer', 'event', 'wedding', 'veterinary', 'pharmacy')


def _norm(url: str) -> str:
    url = (url or '').strip()
    if url and not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _is_social(url: str) -> bool:
    host = (urlparse(url).hostname or '').lower().removeprefix('www.')
    return any(host == s or host.endswith('.' + s) for s in SOCIAL_HOSTS)


def ssl_days_left(host: str, timeout: int = 6) -> int | None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                exp = ss.getpeercert()['notAfter']
        expiry = time.mktime(time.strptime(exp, '%b %d %H:%M:%S %Y %Z'))
        return int((expiry - time.time()) / 86400)
    except Exception:
        return None


def audit_site(url: str, timeout: int = 12) -> dict:
    """Fetch one site and report what it is and isn't doing."""
    out: dict = {'site_status': 0, 'site_ms': 0, 'has_ssl': 0, 'mobile_ok': 0,
                 'has_title': 0, 'has_meta_desc': 0, 'has_h1': 0, 'has_schema': 0,
                 'word_count': 0, 'has_booking': 0, 'has_chat': 0, 'has_form': 0,
                 'has_whatsapp': 0, 'email': '', 'notes': []}
    url = _norm(url)
    if not url:
        out['notes'].append('no url')
        return out

    host = urlparse(url).hostname or ''
    t0 = time.time()
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True,
                         headers={'User-Agent': UA,
                                  'Accept-Language': 'en;q=0.9'})
        out['site_ms'] = int((time.time() - t0) * 1000)
        out['site_status'] = r.status_code
        out['has_ssl'] = 1 if r.url.startswith('https://') else 0
        html = r.text or ''
    except requests.exceptions.SSLError:
        out['notes'].append('ssl error')
        out['site_ms'] = int((time.time() - t0) * 1000)
        return out
    except Exception as e:
        out['notes'].append(f'unreachable: {type(e).__name__}')
        out['site_ms'] = int((time.time() - t0) * 1000)
        return out

    low = html.lower()
    if any(m in low for m in PARKED_MARKERS) and len(html) < 40000:
        out['notes'].append('parked or placeholder')

    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return out

    title = (soup.title.string or '').strip() if soup.title else ''
    out['has_title'] = 1 if len(title) >= 10 else 0
    md = soup.find('meta', attrs={'name': re.compile('^description$', re.I)})
    out['has_meta_desc'] = 1 if md and (md.get('content') or '').strip() else 0
    out['mobile_ok'] = 1 if soup.find('meta', attrs={'name': re.compile('^viewport$', re.I)}) else 0
    out['has_h1'] = 1 if soup.find('h1') else 0
    out['has_schema'] = 1 if ('application/ld+json' in low or 'itemtype' in low) else 0
    out['has_form'] = 1 if soup.find('form') else 0

    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    out['word_count'] = len(soup.get_text(' ', strip=True).split())

    # intent has to appear in a link, a script, or real anchor text
    linky = ' '.join(filter(None, (
        [a.get('href', '') for a in soup.find_all('a', href=True)]
        + [t.get('src', '') for t in soup.find_all(['script', 'iframe'], src=True)]
    ))).lower()
    anchor_text = ' '.join(a.get_text(' ', strip=True)
                           for a in soup.find_all(['a', 'button']))[:4000]
    out['has_booking'] = 1 if (any(b in linky for b in BOOKING_HOSTS)
                               or BOOKING_TEXT.search(anchor_text)) else 0
    out['has_chat'] = 1 if any(c in linky or c in low for c in CHAT) else 0
    out['has_whatsapp'] = 1 if any(w in linky for w in WHATSAPP) else 0

    try:
        out['email'] = harvest_email(html, soup, r.url, timeout)
    except Exception:
        pass

    if host and out['has_ssl']:
        days = ssl_days_left(host)
        if days is not None and days < 14:
            out['notes'].append(f'ssl expires in {days}d')
    return out


EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}')

# addresses that belong to the platform, not the business
EMAIL_JUNK = ('example.com', 'sentry.io', 'wixpress.com', 'wix.com', 'godaddy',
              'squarespace.com', 'shopify.com', 'cloudflare', 'googleapis',
              'jquery', 'bootstrap', 'fontawesome', 'schema.org', 'w3.org',
              'yourdomain', 'domain.com', 'email.com', 'sentry-', 'wordpress.org',
              'gravatar', 'placeholder', 'test.com', 'no-reply', 'noreply',
              'donotreply', 'abuse@', 'postmaster@',
              # theme boilerplate the owner never changed
              'mystore.com', 'yourstore', 'yoursite', 'yourcompany', 'mysite.com',
              'sentry.wixpress', 'menufy.com', 'instacart.com', 'doordash',
              'ubereats', 'grubhub', 'opentable', 'yelp.com', 'tripadvisor',
              # corporate press/PR desks — a franchise inbox, not a buyer
              'press@', 'media@', 'pr@', 'investor', 'careers@', 'jobs@',
              'privacy@', 'legal@', 'compliance@', 'dpo@', 'security@',
              'webmaster@', 'hostmaster@', 'unsubscribe@')

# theme demo content the owner never replaced
PLACEHOLDER_NAME = re.compile(
    r'^(john\.?doe|jane\.?doe|j\.?doe|firstname|lastname|your\.?name|name|'
    r'user|username|someone|somebody|demo|sample|foo|bar|test\d*)@', re.I)

FREE_PROVIDERS = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.uk', 'ymail.com',
    'hotmail.com', 'hotmail.co.uk', 'outlook.com', 'live.com', 'msn.com',
    'aol.com', 'icloud.com', 'me.com', 'mac.com', 'protonmail.com',
    'proton.me', 'gmx.com', 'gmx.net', 'zoho.com', 'mail.com', 'comcast.net',
    'sbcglobal.net', 'verizon.net', 'att.net', 'bellsouth.net', 'cox.net',
    'btinternet.com', 'sky.com', 'virginmedia.com',
}

PREFERRED = ('info@', 'contact@', 'hello@', 'enquiries@', 'enquiry@',
             'reception@', 'admin@', 'office@', 'sales@', 'bookings@',
             'appointments@', 'support@')


def harvest_email(html: str, soup, base_url: str, timeout: int = 8) -> str:
    """
    Pull a contact address off the business's own website.

    Only reads what the business has already published on their own pages —
    the same address a customer would find. Platform and library addresses are
    filtered out, and an address on their own domain wins over a stray gmail.
    """
    found: list[str] = []

    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.lower().startswith('mailto:'):
            addr = href[7:].split('?')[0].strip()
            if addr:
                found.append(addr)

    found += EMAIL_RE.findall(html or '')

    # the contact page usually has it when the home page doesn't
    if not found:
        host = urlparse(base_url)
        for path in ('/contact', '/contact-us', '/contact.html', '/about'):
            try:
                r = requests.get(f'{host.scheme}://{host.netloc}{path}',
                                 timeout=timeout, headers={'User-Agent': UA})
                if r.status_code == 200:
                    found += EMAIL_RE.findall(r.text or '')
                    if found:
                        break
            except Exception:
                continue

    site_host = (urlparse(base_url).hostname or '').removeprefix('www.').lower()
    root = '.'.join(site_host.split('.')[-2:]) if site_host else ''

    clean = []
    for e in found:
        el = e.strip().strip('.').lower()
        if len(el) > 96 or any(j in el for j in EMAIL_JUNK):
            continue
        if re.search(r'\.(png|jpe?g|gif|svg|webp|css|js)$', el):
            continue
        if PLACEHOLDER_NAME.match(el):
            continue
        dom = el.split('@')[-1]
        # An address on someone else's business domain is almost always the
        # web agency that built the site, not the business. Pitching a
        # dentist's marketing agency wastes the send and tips off a
        # competitor. Free-provider addresses are fine — plenty of real
        # owners use gmail.
        if root and not dom.endswith(root) and dom not in FREE_PROVIDERS:
            continue
        if el not in clean:
            clean.append(el)
    if not clean:
        return ''

    def rank(e: str) -> tuple:
        own_domain = 0 if site_host and e.endswith('@' + site_host) else 1
        free = 1 if e.split('@')[-1] in FREE_PROVIDERS else 0
        pref = 0 if any(e.startswith(p) for p in PREFERRED) else 1
        return (own_domain, free, pref, len(e))

    return sorted(clean, key=rank)[0]


def classify(lead: dict, audit: dict, category: str) -> tuple[str, float, list[str]]:
    """Return (offer, score 0-100, human-readable reasons)."""
    reasons: list[str] = []
    cat = (category or '').lower()
    high_intent = any(k in cat for k in HIGH_INTENT)

    # how much this business is worth reaching at all
    rating = lead.get('rating') or 0
    reviews = lead.get('reviews') or 0
    reach = 12 if lead.get('phone_e164') else 0
    traction = min(18, reviews / 10) + (6 if rating >= 4.0 else 0)
    # an implant dentist and a corner shop have the same problem and very
    # different budgets, so the segment's value scales the whole score
    vmul = value_of(category)

    website = (lead.get('website') or '').strip()

    # ---------------------------------------------------- no real website
    if not website:
        reasons.append('No website listed on Google')
        return 'webdev', min(100, (58 + reach + traction) * vmul), reasons
    if _is_social(website):
        reasons.append('Only a social page, no real website')
        return 'webdev', min(100, (55 + reach + traction) * vmul), reasons

    status = audit.get('site_status', 0)
    notes = audit.get('notes', [])

    if status == 0 or status >= 500:
        reasons.append('Website does not load')
        return 'webdev', min(100, (60 + reach + traction) * vmul), reasons
    if status in (403, 404, 410):
        reasons.append(f'Website returns {status}')
        return 'webdev', min(100, (52 + reach + traction) * vmul), reasons
    if any('parked' in n for n in notes):
        reasons.append('Domain is parked or a placeholder page')
        return 'webdev', min(100, (56 + reach + traction) * vmul), reasons
    if not audit.get('mobile_ok') and audit.get('word_count', 0) < 400:
        reasons.append('Not usable on a phone, and almost no content')
        return 'webdev', min(100, (50 + reach + traction) * vmul), reasons

    # ------------------------------------------------------- SEO problems
    seo_faults = []
    if not audit.get('mobile_ok'):
        seo_faults.append('no mobile layout')
    if not audit.get('has_title'):
        seo_faults.append('missing or empty page title')
    if not audit.get('has_meta_desc'):
        seo_faults.append('no meta description')
    if not audit.get('has_h1'):
        seo_faults.append('no H1 heading')
    if not audit.get('has_schema'):
        seo_faults.append('no local-business structured data')
    if not audit.get('has_ssl'):
        seo_faults.append('no HTTPS')
    if audit.get('word_count', 0) < 300:
        seo_faults.append('very thin content')
    if audit.get('site_ms', 0) > 3500:
        seo_faults.append(f"slow to load ({audit['site_ms']/1000:.1f}s)")
    if any('ssl expires' in n for n in notes):
        seo_faults.append('SSL certificate about to expire')

    if len(seo_faults) >= 2:
        reasons.extend(seo_faults)
        severity = min(30, 7 * len(seo_faults))
        return 'seo', min(100, (34 + severity + reach + traction * 0.7) * vmul), reasons

    # ------------------------------------------------- automation gaps
    auto_faults = []
    if not audit.get('has_booking'):
        auto_faults.append('no way to book online')
    if not audit.get('has_chat') and not audit.get('has_whatsapp'):
        auto_faults.append('no chat or WhatsApp button')
    if not audit.get('has_form'):
        auto_faults.append('no enquiry form')

    if high_intent and len(auto_faults) >= 2:
        reasons.extend(auto_faults)
        reasons.append(f'{int(reviews)} reviews — enquiries are being handled by hand')
        return 'automation', min(100, 36 + 8 * len(auto_faults) + reach + traction), reasons

    if seo_faults:
        reasons.extend(seo_faults)
        return 'seo', min(100, 26 + 7 * len(seo_faults) + reach), reasons

    reasons.append('Site covers the basics — softer angle needed')
    return 'other', min(100, (18 + reach + traction * 0.5) * vmul), reasons


class Diagnoser:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store

    def audit_only(self, row) -> tuple:
        """Runs in a worker thread. Touches the network, never the database."""
        lead = dict(row)
        website = (lead.get('website') or '').strip()
        audit = (audit_site(website, self.cfg.limits.audit_timeout_s)
                 if website and not _is_social(website)
                 else {'notes': ['skipped: no site to audit']})
        offer, score, reasons = classify(lead, audit, lead.get('category', ''))
        return lead, audit, offer, score, reasons

    def persist(self, lead, audit, offer, score, reasons) -> dict:
        """Runs on the main thread, where the sqlite connection lives."""
        fields = {k: audit.get(k) for k in (
            'site_status', 'site_ms', 'has_ssl', 'mobile_ok', 'has_title',
            'has_meta_desc', 'has_h1', 'has_schema', 'word_count',
            'has_booking', 'has_chat', 'has_form', 'has_whatsapp')}
        fields.update({
            'audit_notes':  '; '.join(audit.get('notes', [])),
            'offer':        offer,
            'score':        round(score, 1),
            'reasons_json': json.dumps(reasons),
            'diagnosed_at': now(),
            'status':       'diagnosed',
        })
        if audit.get('email') and not (lead.get('email') or '').strip():
            fields['email'] = audit['email']
        self.store.update(lead['id'], **fields)
        return {'id': lead['id'], 'name': lead['name'], 'offer': offer,
                'score': round(score, 1), 'reasons': reasons}

    def one(self, row) -> dict:
        return self.persist(*self.audit_only(row))

    def run(self, market: str | None = None, limit: int = 300) -> dict:
        rows = self.store.pending('diagnose', market, limit)
        if not rows:
            return {'diagnosed': 0}
        results = []
        with ThreadPoolExecutor(max_workers=self.cfg.limits.audit_concurrency) as pool:
            audited = list(pool.map(self.audit_only, rows))
        for a in audited:
            res = self.persist(*a)
            results.append(res)
            print(f"  {res['score']:>5.1f}  {res['offer']:<11} {res['name'][:38]:<40}"
                  f"{res['reasons'][0][:46] if res['reasons'] else ''}")
        tally: dict = {}
        for r in results:
            tally[r['offer']] = tally.get(r['offer'], 0) + 1
        return {'diagnosed': len(results), 'by_offer': tally}
