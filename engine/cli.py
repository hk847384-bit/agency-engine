#!/usr/bin/env python3
"""
agency-engine — find local businesses, work out what they need, build the proof,
write the pitch.

    python -m engine.cli find      --market pk --cities Multan --limit 40
    python -m engine.cli diagnose  --market pk
    python -m engine.cli demo      --market pk --limit 20
    python -m engine.cli pitch     --channel email --dry-run
    python -m engine.cli pitch     --channel whatsapp            # always drafts
    python -m engine.cli export    --out out/leads.csv
    python -m engine.cli stats
    python -m engine.cli suppress  --email someone@example.com --reason "asked to stop"
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .config import Config
from .store import Store


def _ctx(args):
    cfg = Config.load(args.config) if args.config else Config.load()
    return cfg, Store(cfg.db_path)


def cmd_find(args):
    from .find import Finder
    cfg, store = _ctx(args)
    res = Finder(cfg, store).run(
        args.market,
        cities=args.cities or None,
        categories=args.categories or None,
        per_query=args.limit,
        use_overpass=args.overpass,
        source=args.source)
    print(json.dumps(res, indent=2))


def cmd_diagnose(args):
    from .diagnose import Diagnoser
    cfg, store = _ctx(args)
    print(json.dumps(Diagnoser(cfg, store).run(args.market, args.limit), indent=2))


def cmd_demo(args):
    from .demo import DemoBuilder
    cfg, store = _ctx(args)
    res = DemoBuilder(cfg, store).run(args.market, args.limit)
    print(f"\nbuilt {res['built']} demo sites in {cfg.demo_dir}")


def cmd_pitch(args):
    from .pitch import Pitcher
    cfg, store = _ctx(args)
    res = Pitcher(cfg, store).run(
        channel=args.channel, market=args.market, limit=args.limit,
        dry_run=not args.send, min_score=args.min_score)
    print('\n' + json.dumps(res['counts'], indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(res['drafts'], indent=2), encoding='utf-8')
        print(f"drafts written to {args.out}")


def cmd_export(args):
    cfg, store = _ctx(args)
    rows = store.db.execute(
        'SELECT id,name,category,city,market,offer,score,phone_e164,email,website,'
        'demo_url,status,touches,audit_notes,reasons_json FROM leads '
        'ORDER BY score DESC NULLS LAST').fetchall()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(rows[0].keys() if rows else [])
        for r in rows:
            w.writerow(list(r))
    print(f'exported {len(rows)} leads to {out}')


def cmd_stats(args):
    cfg, store = _ctx(args)
    s = store.stats()
    width = max(len(k) for k in s)
    print()
    for k, v in s.items():
        print(f'  {k:<{width}}  {v}')
    print()


def cmd_suppress(args):
    cfg, store = _ctx(args)
    n = 0
    for kind in ('email', 'phone', 'domain', 'place_id'):
        val = getattr(args, kind, None)
        if val:
            store.suppress(kind, val, args.reason)
            n += 1
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            line = line.strip()
            if line:
                store.suppress('email' if '@' in line else 'phone', line, args.reason)
                n += 1
    print(f'suppressed {n} entries')


def main(argv=None):
    p = argparse.ArgumentParser(prog='agency-engine')
    p.add_argument('--config')
    sub = p.add_subparsers(dest='cmd', required=True)

    f = sub.add_parser('find', help='source businesses')
    f.add_argument('--market', required=True)
    f.add_argument('--cities', nargs='*')
    f.add_argument('--categories', nargs='*')
    f.add_argument('--limit', type=int, default=60)
    f.add_argument('--overpass', action='store_true', help='also pull free OSM data')
    f.add_argument('--source', choices=['auto', 'places', 'osm'], default='auto',
                   help='osm needs no API key and no billing account')
    f.set_defaults(fn=cmd_find)

    d = sub.add_parser('diagnose', help='audit sites and route to an offer')
    d.add_argument('--market')
    d.add_argument('--limit', type=int, default=300)
    d.set_defaults(fn=cmd_diagnose)

    b = sub.add_parser('demo', help='build sample sites for web-dev leads')
    b.add_argument('--market')
    b.add_argument('--limit', type=int, default=50)
    b.set_defaults(fn=cmd_demo)

    m = sub.add_parser('pitch', help='write (and optionally send) the outreach')
    m.add_argument('--channel', choices=['email', 'whatsapp'], default='email')
    m.add_argument('--market')
    m.add_argument('--limit', type=int, default=50)
    m.add_argument('--min-score', type=float, default=0.0, dest='min_score')
    m.add_argument('--send', action='store_true',
                   help='actually send (email only; WhatsApp always drafts)')
    m.add_argument('--out', help='write drafts to this JSON file')
    m.set_defaults(fn=cmd_pitch)

    e = sub.add_parser('export')
    e.add_argument('--out', default='out/leads.csv')
    e.set_defaults(fn=cmd_export)

    s = sub.add_parser('stats')
    s.set_defaults(fn=cmd_stats)

    x = sub.add_parser('suppress', help='never contact these again')
    x.add_argument('--email')
    x.add_argument('--phone')
    x.add_argument('--domain')
    x.add_argument('--place-id', dest='place_id')
    x.add_argument('--file', help='one address or number per line')
    x.add_argument('--reason', default='manual')
    x.set_defaults(fn=cmd_suppress)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
