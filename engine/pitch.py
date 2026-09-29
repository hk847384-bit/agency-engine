"""
PITCH — turn a diagnosis into a message, and get it out safely.

Two rules shape this file.

Email is the channel that scales, so it carries the volume, with per-hour and
per-day caps, a permanent suppression list, and an unsubscribe line on every
message. Sending faster than a human plausibly could is how a domain's
reputation dies, and a dead sending domain takes months to rebuild.

WhatsApp does not scale and pretending otherwise gets the number banned.
Business-initiated messages to people who never opted in break WhatsApp's
Business Messaging Policy. So the default here is to *draft* — we write the
message and a wa.me link, and a person presses send. Auto-send exists but is
off unless you explicitly turn it on, and it should never run on the number
your live chatbot uses.
"""

from __future__ import annotations

import json
import re
import smtplib
import time
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .store import now

ROOT = Path(__file__).resolve().parent.parent

PROBLEM_SHORT = {
    'no website': "doesn't have a website yet",
    'social': 'only has a Facebook page, not a website of its own',
    'dead': "has a website that doesn't load",
    'parked': 'has a domain that just shows a placeholder page',
    'mobile': "has a site that doesn't work properly on a phone",
}

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def problem_short(reasons: list[str]) -> str:
    joined = ' '.join(reasons).lower()
    if 'no website listed' in joined:
        return PROBLEM_SHORT['no website']
    if 'social page' in joined:
        return PROBLEM_SHORT['social']
    if 'does not load' in joined or 'returns' in joined:
        return PROBLEM_SHORT['dead']
    if 'parked' in joined:
        return PROBLEM_SHORT['parked']
    if 'phone' in joined:
        return PROBLEM_SHORT['mobile']
    return "doesn't have much of a web presence yet"


class Pitcher:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.env = Environment(
            loader=FileSystemLoader(str(ROOT / 'templates' / 'msg')),
            autoescape=select_autoescape(enabled_extensions=(), default=False),
            trim_blocks=False, lstrip_blocks=False)

    # ------------------------------------------------------------ compose
    def compose(self, row, channel: str) -> dict:
        lead = dict(row)
        offer = lead.get('offer') or 'other'
        market = self.cfg.market(lead['market']) if lead.get('market') else None
        reasons = json.loads(lead.get('reasons_json') or '[]')
        price = {
            'webdev': getattr(market, 'price_webdev', '') if market else '',
            'seo': getattr(market, 'price_seo', '') if market else '',
            'automation': getattr(market, 'price_automation', '') if market else '',
        }.get(offer, '')

        unsub = ''
        if channel == 'email':
            unsub = (f'Not interested? Reply STOP and you will not hear from me again'
                     + (f', or unsubscribe here: {self.cfg.unsubscribe_url}'
                        if self.cfg.unsubscribe_url else '') + '.')

        ctx = {
            'biz': lead,
            'contact_name': '',
            'reasons': reasons,
            'problem_short': problem_short(reasons),
            'demo_url': lead.get('demo_url') or '',
            'website_host': (urlparse(lead.get('website') or '').hostname or '').removeprefix('www.'),
            'price': price or 'a fair fixed price',
            'agency_name': self.cfg.agency_name,
            'agency_person': self.cfg.agency_person,
            'agency_phone': self.cfg.agency_phone,
            'unsubscribe_line': unsub,
            'original_subject': '',
        }

        tpl = f'{"email" if channel == "email" else "wa"}_{offer}.j2'
        text = self.env.get_template(tpl).render(**ctx).strip()

        subject = ''
        if channel == 'email' and text.lower().startswith('subject:'):
            first, _, rest = text.partition('\n')
            subject = first.split(':', 1)[1].strip()
            text = rest.strip()
        return {'subject': subject, 'body': text, 'offer': offer}

    # -------------------------------------------------------------- email
    def _smtp(self):
        if not self.cfg.smtp_host:
            raise RuntimeError('smtp_host is not configured')
        s = smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=30)
        s.starttls()
        if self.cfg.smtp_user:
            s.login(self.cfg.smtp_user, self.cfg.smtp_pass)
        return s

    def send_email(self, row, msg: dict, dry_run: bool = True) -> tuple[str, str]:
        lead = dict(row)
        to = (lead.get('email') or '').strip()
        if not to or not EMAIL_RE.fullmatch(to):
            return 'skipped', 'no valid email address'
        if self.store.is_suppressed(email=to,
                                    domain=to.split('@')[-1],
                                    place_id=lead.get('place_id')):
            return 'skipped', 'suppressed'
        if self.store.address_used(to, exclude_lead=lead.get('id')):
            return 'skipped', 'address already contacted under another lead'

        lim = self.cfg.limits
        if self.store.sent_today('email') >= lim.emails_per_day:
            return 'skipped', 'daily email cap reached'
        if self.store.sent_last_hour('email') >= lim.emails_per_hour:
            return 'skipped', 'hourly email cap reached'
        if dry_run:
            return 'drafted', ''

        mime = MIMEText(msg['body'], 'plain', 'utf-8')
        mime['Subject'] = msg['subject'] or f"About {lead['name']}"
        mime['From'] = formataddr((self.cfg.agency_name,
                                   self.cfg.smtp_from or self.cfg.agency_email))
        mime['To'] = to
        mime['Reply-To'] = self.cfg.agency_email
        mime['Message-ID'] = make_msgid()
        if self.cfg.unsubscribe_url:
            mime['List-Unsubscribe'] = f'<{self.cfg.unsubscribe_url}>'
            mime['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
        try:
            with self._smtp() as s:
                s.send_message(mime)
            return 'sent', ''
        except Exception as e:
            return 'failed', f'{type(e).__name__}: {e}'

    # ----------------------------------------------------------- whatsapp
    def whatsapp(self, row, msg: dict, dry_run: bool = True) -> tuple[str, str]:
        """
        Draft by default. We produce the text and a click-to-send link; a
        person decides whether to send it. Auto-sending cold WhatsApp to
        numbers that never opted in is what gets a number permanently banned,
        so it stays behind an explicit flag.
        """
        lead = dict(row)
        phone = (lead.get('phone_e164') or '').lstrip('+')
        if not phone:
            return 'skipped', 'no phone number'
        if self.store.is_suppressed(phone=lead.get('phone_e164'),
                                    place_id=lead.get('place_id')):
            return 'skipped', 'suppressed'
        if not (self.cfg.whatsapp_autosend and not dry_run):
            return 'drafted', ''
        if self.store.sent_today('whatsapp') >= self.cfg.limits.whatsapp_per_day:
            return 'skipped', 'daily whatsapp cap reached'
        return 'skipped', ('auto-send not implemented on purpose — wire your own '
                           'approved-template call here once you have opt-in')

    @staticmethod
    def wa_link(row, msg: dict) -> str:
        from urllib.parse import quote
        phone = (dict(row).get('phone_e164') or '').lstrip('+')
        return f"https://wa.me/{phone}?text={quote(msg['body'][:1500])}" if phone else ''

    # --------------------------------------------------------------- run
    def run(self, channel: str = 'email', market: str | None = None,
            limit: int = 50, dry_run: bool = True,
            min_score: float = 0.0) -> dict:
        rows = [r for r in self.store.pending('pitch', market, limit * 3,
                                              channel=channel)
                if (r['score'] or 0) >= min_score][:limit]
        counts: dict = {}
        drafts = []
        reasons: dict = {}

        if not rows:
            pool = len(self.store.pending('pitch', market, 10000))
            addressable = len(self.store.pending('pitch', market, 10000,
                                                 channel=channel))
            print(f'  nothing to pitch on {channel}.')
            print(f'    {pool} leads are at the pitch stage')
            print(f'    {addressable} of them have a {channel} address')
            if addressable:
                print(f'    but none of those scored {min_score} or above '
                      f'— lower --min-score')
            else:
                print('    run diagnose to harvest addresses, or pitch '
                      'on whatsapp instead (every lead has a phone)')
            return {'channel': channel, 'counts': {}, 'drafts': []}

        for row in rows:
            msg = self.compose(row, channel)
            if channel == 'email':
                status, err = self.send_email(row, msg, dry_run)
            else:
                status, err = self.whatsapp(row, msg, dry_run)
                msg['wa_link'] = self.wa_link(row, msg)

            self.store.log_touch(row['id'], channel, 'first', msg['subject'],
                                 msg['body'], status, err)
            counts[status] = counts.get(status, 0) + 1
            if status == 'skipped' and err:
                reasons[err] = reasons.get(err, 0) + 1
            if status in ('drafted', 'sent'):
                drafts.append({'id': row['id'], 'name': row['name'],
                               'offer': msg['offer'], 'score': row['score'],
                               'subject': msg['subject'], 'body': msg['body'],
                               'wa_link': msg.get('wa_link', ''),
                               'to': row['email'] or row['phone_e164'] or ''})
            flag = {'sent': 'SENT', 'drafted': 'draft', 'skipped': 'skip',
                    'failed': 'FAIL'}[status]
            print(f"  {flag:<6} {row['name'][:38]:<40} {msg['offer']:<11}"
                  f"{(err or msg['subject'])[:44]}")
            if status == 'sent':
                time.sleep(max(1, 3600 // max(1, self.cfg.limits.emails_per_hour)))

        if reasons:
            print('\n  skipped, and why:')
            for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
                print(f'    {n:>4}  {why}')
        print(f"\n  {len(drafts)} written of {len(rows)} considered")

        return {'channel': channel, 'counts': counts, 'drafts': drafts}
