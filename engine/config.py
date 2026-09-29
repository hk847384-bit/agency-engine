"""Configuration, loaded from YAML with environment-variable overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / 'config.yaml'


@dataclass
class Market:
    """One geography we prospect in. Channel and pricing differ per market."""

    name: str
    country: str
    cities: list[str] = field(default_factory=list)
    language: str = 'en'
    currency: str = 'USD'
    primary_channel: str = 'email'          # email | whatsapp | manual
    categories: list[str] = field(default_factory=list)
    price_webdev: str = ''
    price_seo: str = ''
    price_automation: str = ''


@dataclass
class Limits:
    """Guardrails. These exist so the system stays usable for years, not days."""

    emails_per_day: int = 120
    emails_per_hour: int = 20
    whatsapp_per_day: int = 0               # 0 = draft only, never auto-send
    places_requests_per_run: int = 300
    audit_concurrency: int = 6
    audit_timeout_s: int = 12
    min_days_between_touches: int = 4
    max_touches_per_lead: int = 3


@dataclass
class Config:
    db_path: str = str(ROOT / 'out' / 'leads.db')
    demo_dir: str = str(ROOT / 'out' / 'demos')
    demo_base_url: str = 'https://demos.example.com'
    agency_name: str = 'Your Agency'
    agency_person: str = 'Imran'
    agency_email: str = 'hello@example.com'
    agency_phone: str = ''
    # CAN-SPAM (US) and PECR/GDPR (UK/EU) both require a real postal address
    # in every commercial email. Without it the send is unlawful, however
    # good the copy is — so the pitcher refuses to send until it is set.
    agency_address: str = ''
    agency_site: str = ''
    google_places_key: str = ''
    serp_api_key: str = ''                  # optional, for real rank checks
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_pass: str = ''
    smtp_from: str = ''
    unsubscribe_url: str = ''
    whatsapp_autosend: bool = False
    markets: list[Market] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> 'Config':
        path = Path(path)
        raw: dict = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text()) or {}

        markets = [Market(**m) for m in raw.pop('markets', [])]
        limits = Limits(**raw.pop('limits', {}))
        cfg = cls(markets=markets, limits=limits,
                  **{k: v for k, v in raw.items() if k in cls.__annotations__})

        # environment always wins, so keys never have to live in the YAML
        for env, attr in (
                ('GOOGLE_PLACES_KEY', 'google_places_key'),
                ('SERP_API_KEY', 'serp_api_key'),
                ('SMTP_HOST', 'smtp_host'),
                ('SMTP_USER', 'smtp_user'),
                ('SMTP_PASS', 'smtp_pass'),
                ('SMTP_FROM', 'smtp_from'),
        ):
            if os.environ.get(env):
                setattr(cfg, attr, os.environ[env])
        if os.environ.get('SMTP_PORT'):
            cfg.smtp_port = int(os.environ['SMTP_PORT'])

        Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.demo_dir).mkdir(parents=True, exist_ok=True)
        return cfg

    def market(self, name: str) -> Market:
        for m in self.markets:
            if m.name == name:
                return m
        raise KeyError(f'no market named {name!r}')
