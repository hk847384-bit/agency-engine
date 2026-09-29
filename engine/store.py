"""
SQLite state.

Everything the pipeline learns about a lead lives here, so a run can be stopped
and resumed, a lead is never sourced or contacted twice, and an opt-out is
permanent across every future run.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY,
    place_id        TEXT UNIQUE,            -- Google Places id, our dedupe key
    source          TEXT,                   -- places | overpass | import
    market          TEXT,
    city            TEXT,
    name            TEXT NOT NULL,
    category        TEXT,
    address         TEXT,
    lat             REAL,
    lng             REAL,
    phone           TEXT,
    phone_e164      TEXT,
    website         TEXT,
    rating          REAL,
    reviews         INTEGER,
    hours_json      TEXT,
    photos_json     TEXT,
    raw_json        TEXT,
    found_at        TEXT,

    -- filled in by the diagnosis pass
    diagnosed_at    TEXT,
    site_status     INTEGER,
    site_ms         INTEGER,
    has_ssl         INTEGER,
    mobile_ok       INTEGER,
    has_title       INTEGER,
    has_meta_desc   INTEGER,
    has_h1          INTEGER,
    has_schema      INTEGER,
    word_count      INTEGER,
    has_booking     INTEGER,
    has_chat        INTEGER,
    has_form        INTEGER,
    has_whatsapp    INTEGER,
    audit_notes     TEXT,
    offer           TEXT,                   -- webdev | seo | automation | other
    score           REAL,
    reasons_json    TEXT,

    demo_path       TEXT,
    demo_url        TEXT,

    status          TEXT DEFAULT 'new',     -- new|diagnosed|demo|queued|contacted|replied|won|lost|skip
    touches         INTEGER DEFAULT 0,
    last_touch_at   TEXT,
    email           TEXT
);

CREATE TABLE IF NOT EXISTS touches (
    id          INTEGER PRIMARY KEY,
    lead_id     INTEGER REFERENCES leads(id),
    channel     TEXT,                       -- email | whatsapp | manual
    kind        TEXT,                       -- first | followup1 | followup2
    subject     TEXT,
    body        TEXT,
    sent_at     TEXT,
    status      TEXT,                       -- drafted | sent | failed | skipped
    error       TEXT
);

CREATE TABLE IF NOT EXISTS suppression (
    id          INTEGER PRIMARY KEY,
    kind        TEXT,                       -- email | phone | domain | place_id
    value       TEXT,
    reason      TEXT,
    added_at    TEXT,
    UNIQUE(kind, value)
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_offer  ON leads(offer);
CREATE INDEX IF NOT EXISTS idx_leads_market ON leads(market);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    @contextmanager
    def tx(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------- leads
    def upsert_lead(self, rec: dict) -> int:
        """Insert a freshly found business, or leave an existing one untouched."""
        cols = ('place_id', 'source', 'market', 'city', 'name', 'category',
                'address', 'lat', 'lng', 'phone', 'phone_e164', 'website',
                'rating', 'reviews', 'hours_json', 'photos_json', 'raw_json')
        vals = [rec.get(c) for c in cols]
        with self.tx() as db:
            cur = db.execute(
                f"INSERT INTO leads ({','.join(cols)}, found_at) "
                f"VALUES ({','.join('?' * len(cols))}, ?) "
                f"ON CONFLICT(place_id) DO NOTHING",
                vals + [now()])
            if cur.lastrowid:
                return cur.lastrowid
            row = db.execute('SELECT id FROM leads WHERE place_id=?',
                             (rec.get('place_id'),)).fetchone()
            return row['id'] if row else 0

    def update(self, lead_id: int, **fields) -> None:
        if not fields:
            return
        sets = ','.join(f'{k}=?' for k in fields)
        with self.tx() as db:
            db.execute(f'UPDATE leads SET {sets} WHERE id=?',
                       list(fields.values()) + [lead_id])

    def pending(self, stage: str, market: str | None = None,
                limit: int = 500, channel: str | None = None) -> list[sqlite3.Row]:
        """
        Leads waiting for a given stage of the pipeline.

        `channel` matters more than it looks. Score and contactability pull in
        opposite directions: a lead scores highest when it has NO website —
        which is exactly the lead with no site to harvest an email from. Order
        by score alone and the first forty rows are all unreachable, every one
        gets skipped, and the run produces an empty file with no error.
        So the channel's address is a condition of selection, not a thing we
        discover after choosing.
        """
        where = {
            'diagnose': "status='new'",
            'demo':     "status='diagnosed' AND offer='webdev'",
            'pitch':    "status IN ('diagnosed','demo')",
        }[stage]
        sql = f'SELECT * FROM leads WHERE {where}'
        args: list = []
        if channel == 'email':
            sql += " AND email IS NOT NULL AND TRIM(email) != ''"
        elif channel == 'whatsapp':
            sql += " AND phone_e164 IS NOT NULL AND TRIM(phone_e164) != ''"
        if market:
            sql += ' AND market=?'
            args.append(market)
        sql += ' ORDER BY score DESC NULLS LAST, id LIMIT ?'
        args.append(limit)
        return self.db.execute(sql, args).fetchall()

    def due_for_followup(self, min_days: int, max_touches: int,
                         limit: int = 200) -> list[sqlite3.Row]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=min_days)).isoformat()
        return self.db.execute(
            "SELECT * FROM leads WHERE status='contacted' AND touches < ? "
            "AND (last_touch_at IS NULL OR last_touch_at < ?) "
            "ORDER BY score DESC LIMIT ?",
            (max_touches, cutoff, limit)).fetchall()

    # -------------------------------------------------------- suppression
    def suppress(self, kind: str, value: str, reason: str = '') -> None:
        if not value:
            return
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO suppression (kind,value,reason,added_at) '
                       'VALUES (?,?,?,?)', (kind, value.strip().lower(), reason, now()))

    def is_suppressed(self, **kv) -> bool:
        for kind, value in kv.items():
            if not value:
                continue
            row = self.db.execute(
                'SELECT 1 FROM suppression WHERE kind=? AND value=?',
                (kind, str(value).strip().lower())).fetchone()
            if row:
                return True
        return False

    # ------------------------------------------------------------ touches
    def log_touch(self, lead_id: int, channel: str, kind: str, subject: str,
                  body: str, status: str, error: str = '') -> None:
        with self.tx() as db:
            db.execute(
                'INSERT INTO touches (lead_id,channel,kind,subject,body,sent_at,status,error) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (lead_id, channel, kind, subject, body, now(), status, error))
            if status == 'sent':
                db.execute('UPDATE leads SET status=?, touches=touches+1, last_touch_at=? '
                           'WHERE id=?', ('contacted', now(), lead_id))

    def address_used(self, addr: str, exclude_lead: int | None = None) -> bool:
        """
        Has this exact address already been written to, under ANY lead?

        Two branches of the same business share one inbox. Without this the
        engine would send the same cold pitch to that inbox once per branch,
        which is the fastest way to get a sending domain blacklisted.
        """
        a = (addr or '').strip().lower()
        if not a:
            return False
        # scoped to email: a WhatsApp draft for the same business is not a
        # reason to withhold the email
        sql = ("SELECT 1 FROM touches t JOIN leads l ON l.id = t.lead_id "
               "WHERE LOWER(l.email) = ? AND t.channel = 'email' "
               "AND t.status IN ('sent','drafted')")
        args: list = [a]
        if exclude_lead:
            sql += ' AND t.lead_id != ?'
            args.append(exclude_lead)
        return self.db.execute(sql + ' LIMIT 1', args).fetchone() is not None

    def sent_today(self, channel: str) -> int:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                   microsecond=0).isoformat()
        row = self.db.execute(
            "SELECT COUNT(*) c FROM touches WHERE channel=? AND status='sent' "
            "AND sent_at >= ?", (channel, start)).fetchone()
        return row['c']

    def sent_last_hour(self, channel: str) -> int:
        start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        row = self.db.execute(
            "SELECT COUNT(*) c FROM touches WHERE channel=? AND status='sent' "
            "AND sent_at >= ?", (channel, start)).fetchone()
        return row['c']

    # -------------------------------------------------------------- stats
    def stats(self) -> dict:
        q = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]
        return {
            'leads':        q('SELECT COUNT(*) FROM leads'),
            'new':          q("SELECT COUNT(*) FROM leads WHERE status='new'"),
            'diagnosed':    q("SELECT COUNT(*) FROM leads WHERE status='diagnosed'"),
            'demo':         q("SELECT COUNT(*) FROM leads WHERE status='demo'"),
            'contacted':    q("SELECT COUNT(*) FROM leads WHERE status='contacted'"),
            'replied':      q("SELECT COUNT(*) FROM leads WHERE status='replied'"),
            'won':          q("SELECT COUNT(*) FROM leads WHERE status='won'"),
            'webdev':       q("SELECT COUNT(*) FROM leads WHERE offer='webdev'"),
            'seo':          q("SELECT COUNT(*) FROM leads WHERE offer='seo'"),
            'automation':   q("SELECT COUNT(*) FROM leads WHERE offer='automation'"),
            'other':        q("SELECT COUNT(*) FROM leads WHERE offer='other'"),
            'suppressed':   q('SELECT COUNT(*) FROM suppression'),
        }
