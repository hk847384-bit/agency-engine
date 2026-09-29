# Agency Engine

Find local businesses, work out what each one actually needs, build the proof,
write the pitch.

The reel this is modelled on does one thing: checks whether a business has a
website, and if not, builds a sample and WhatsApps it to them. That works, but
it only ever sells one service. You sell four, so the pipeline here **diagnoses**
before it pitches and routes each business to the right offer.

```
FIND ──▶ DIAGNOSE ──▶ BUILD ──▶ PITCH
                │
                ├── no site / dead site / Facebook page only ──▶ web development
                ├── real site, but unrankable                 ──▶ SEO
                ├── good site, everything answered by hand    ──▶ AI automation
                └── solid site, basics covered                ──▶ softer approach
```

---

## Install

```bash
pip install -r requirements.txt
cp config.yaml config.yaml.local     # then edit
```

Keys belong in the environment, never in the YAML:

```bash
export GOOGLE_PLACES_KEY=...
export SMTP_HOST=smtp.yourprovider.com
export SMTP_USER=... SMTP_PASS=... SMTP_FROM=outreach@yoursendingdomain.com
```

## Run it

```bash
python3 -m engine.cli find     --market pk --cities Multan Lahore --limit 40
python3 -m engine.cli diagnose
python3 -m engine.cli demo     --limit 25
python3 -m engine.cli pitch    --channel email --min-score 45          # drafts
python3 -m engine.cli pitch    --channel email --min-score 45 --send   # sends
python3 -m engine.cli pitch    --channel whatsapp --out out/wa.json    # always drafts
python3 -m engine.cli stats
python3 -m engine.cli export   --out out/leads.csv
```

Every stage is resumable. Nothing is sourced twice, nothing is contacted twice,
and an opt-out is permanent across every future run.

---

## Run it for the first time

### 0. Put it somewhere with room

Your C: drive is tight. Unzip to D:.

```powershell
cd D:\agency-engine
python --version          # need 3.10+; get it from python.org if missing
pip install -r requirements.txt
```

### 1. A real run, right now, costing nothing

OpenStreetMap needs no key, no billing account, no signup:

```powershell
python -m engine.cli find --market pk --cities Multan --source osm
python -m engine.cli diagnose
python -m engine.cli stats
```

That sources real businesses in Multan, audits whichever have websites, harvests
their published contact email, and sorts them into the four offers. Open
`out/leads.csv` after `python -m engine.cli export` and you have a working call
sheet. No API key involved.

OSM coverage is patchy and carries no ratings or photos, so the demo sites come
out plainer. It is enough to prove the machine runs and to start calling.

### 2. Turn on Google Places (better data, costs money)

Places is what gives you ratings, review counts, opening hours and the
photographs that make a demo site look like the business's own.

1. console.cloud.google.com → create a project
2. Enable **Places API (New)**
3. Credentials → Create credentials → API key
4. Restrict the key to the Places API — an unrestricted key that leaks gets
   used by someone else on your card
5. Enable billing. Google Maps Platform includes a recurring monthly free
   credit; check the current per-1,000 rate on their pricing page and set a
   **budget alert** before you run anything

```powershell
setx GOOGLE_PLACES_KEY "AIza..."      # reopen the terminal afterwards
python -m engine.cli find --market pk --cities Multan Lahore --limit 40
python -m engine.cli diagnose
python -m engine.cli demo
```

`places_requests_per_run` in `config.yaml` is the hard stop on spend per run.
Leave it low until you have seen a bill.

### 3. Put the demo sites online

The links in your messages have to resolve. Any static host works and the free
tiers are plenty:

- **Cloudflare Pages** — `npx wrangler pages deploy out/demos --project-name demos`
- **Netlify** — drag `out/demos` onto app.netlify.com/drop
- your own server — `scp -r out/demos/* user@host:/var/www/demos/`

Then set `demo_base_url` in `config.yaml` to match. Check one link in a browser
before you send anything.

### 4. Email

Use a **separate domain** from your client mail. If outreach burns the
reputation of the domain your real business email runs on, you lose both.

1. Buy something close to your brand — `alphaagency.co`, `getalphaagency.com`
2. Point it at a provider (Zoho Mail is cheap; Google Workspace works)
3. Set **SPF, DKIM and DMARC** — without all three you land in spam by default
4. Set the credentials:

```powershell
setx SMTP_HOST "smtp.zoho.com"
setx SMTP_USER "outreach@yourseconddomain.com"
setx SMTP_PASS "..."
setx SMTP_FROM "outreach@yourseconddomain.com"
```

Then read before you send:

```powershell
python -m engine.cli pitch --channel email --min-score 45 --out out\drafts.json
```

Open `out/drafts.json`. Read ten of them properly. Rewrite the templates in
`templates/msg/` in your own voice. Only then:

```powershell
python -m engine.cli pitch --channel email --min-score 45 --send
```

**Warm up or waste the domain.** Drop `emails_per_day` to 10 for the first
week, 25 the second, 50 the third, then 120. A new domain that sends 120 cold
emails on day one is filtered permanently, and rebuilding takes months.

### 5. WhatsApp — the part you do by hand

```powershell
python -m engine.cli pitch --channel whatsapp --min-score 60 --out out\wa.json
```

Every entry has a `wa_link`. Click it, the message is pre-filled in WhatsApp
Web, you read it and press send. Twenty minutes gets through about forty.

That manual step is the whole reason this keeps working. The reel shows dozens
of identical outbound messages — that pattern is exactly what Meta's spam
detection is built to catch, and the ban is on the number, permanently. Yours
is the number running the clinic bot.

### 6. Run it on a schedule

Import `n8n/agency-engine.json` into the n8n you already have. Set `ENGINE_DIR`
and `DEMO_DEPLOY_TARGET` as variables and put the keys in the n8n environment.

Or, without n8n, Windows Task Scheduler on a one-line batch file:

```bat
cd /d D:\agency-engine
python -m engine.cli find --market pk --limit 40
python -m engine.cli diagnose
python -m engine.cli demo
python -m engine.cli pitch --channel email --min-score 45 --send
python -m engine.cli export --out out\leads.csv
```

### A sane first fortnight

| | |
|---|---|
| Days 1–2 | OSM run, read the CSV, call twenty leads yourself |
| Day 3 | Places key, proper demos, host them |
| Days 4–7 | 10 emails/day, rewrite templates from the replies |
| Week 2 | 25/day, add the WhatsApp manual loop, schedule it |

Call the first twenty yourself before you automate anything. You will learn
which objection comes back every time, and that belongs in the templates.

---

## How the diagnosis works

`diagnose` fetches each lead's website and records what it finds: HTTP status,
load time, HTTPS, mobile viewport, title, meta description, H1, structured data,
word count, and whether anything on the page can take a booking, open a chat or
capture an enquiry.

Then it routes:

| What it found | Offer |
|---|---|
| No website on the Google listing | **web dev** |
| "Website" is a Facebook/Instagram/Linktree page | **web dev** |
| Domain doesn't resolve, 5xx, 404, or is parked | **web dev** |
| No mobile layout *and* under 400 words | **web dev** |
| Two or more of: no mobile, no title, no meta, no H1, no schema, no HTTPS, thin content, slow | **SEO** |
| Site is fine, but no booking + no chat/WhatsApp + no form, in a high-intent category | **automation** |
| Everything covered | **other** |

Scores combine severity of the problem, whether you can actually reach them
(phone on file), and how much traction they have (review count, rating) — a
business with 300 reviews and no booking link is worth far more of your time
than one with four reviews and the same gap.

Verified against fixtures for all four branches. One thing worth knowing: the
booking check looks at link targets, script sources and real anchor text, not
the word "appointment" anywhere on the page — that gave false positives on
ordinary body copy.

## The demo sites

Generated from the Places data you already paid for: their name, category,
rating, review count, address, opening hours and their own photographs, inlined
as data URIs so each demo is one self-contained file that keeps working after
the photo reference expires. Dark-mode aware, mobile-first, structured data
included, WhatsApp button wired to their own number.

Every page carries a footer stating plainly that it's an unpublished sample
built by you, that nothing is live, and that you'll delete it on request. Keep
that. A mock-up that looks like a real published site invites exactly the
complaint you don't want.

## Staying alive

Two channels, two very different risk profiles.

**Email** carries the volume. Capped at 120/day and 20/hour in `config.yaml`,
with a permanent suppression list, `List-Unsubscribe` headers and a STOP line on
every message. Warm a new sending domain up over three weeks — 10/day, then
25/day, then step up. Use a domain that is *not* the one your client mail runs on.

**WhatsApp drafts only.** The engine writes the message and a `wa.me` link; a
person sends it. This is deliberate. Business-initiated messages to people who
never opted in break Meta's Business Messaging Policy, bans are usually
permanent, and the number you'd lose is the one running your clinic chatbot.
`whatsapp_autosend` exists in the config and is off; if you ever turn it on,
put it on a separate SIM and expect to lose it.

Data sources are licensed or open: Google Places API and OpenStreetMap. No
scraping of Google Maps — it breaks their terms, gets the IP blocked, and the
API returns the photos and hours the demo builder needs anyway.

## Running it from n8n

`n8n/agency-engine.json` imports as a workflow with three schedules: source and
build in the morning, outreach twice a day, numbers at six. Set `ENGINE_DIR`
and `DEMO_DEPLOY_TARGET` as n8n variables and put the API keys in the n8n
environment.

Leave `--send` off the email node for the first week and read `out/sent.json`
instead. You want to see what it's about to say before it says it to 120 people.

## Layout

```
engine/config.py     config + per-market pricing
engine/store.py      SQLite: leads, touches, suppression
engine/find.py       Google Places + OpenStreetMap
engine/diagnose.py   site audit and offer routing
engine/demo.py       sample site generator
engine/pitch.py      message composition, sending, caps
engine/cli.py        command line
templates/           demo site + per-offer message templates
n8n/                 workflow JSON
```

## What to change first

The message templates in `templates/msg/` are where your close rate lives. They
are written to sound like one person who looked at one business, because that is
the only reason anyone replies. Rewrite them in your own voice before you send a
single one — and keep the offer to delete the demo. It is what makes the whole
approach defensible.
