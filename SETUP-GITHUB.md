# Running it automatically on GitHub (free)

No server, no laptop. GitHub runs it on a schedule in their cloud.

## One-time setup, about 15 minutes

### 1. Put the code on GitHub — **private repo**

It will hold business contact details, so private is not optional.

```bash
cd agency-engine
git init
git add -A
git commit -m "agency engine"
gh repo create agency-engine --private --source=. --push
```

No `gh` CLI? Create an empty private repo on github.com, then:

```bash
git remote add origin https://github.com/YOURNAME/agency-engine.git
git branch -M main && git push -u origin main
```

### 2. Add your keys as Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | What it is |
|---|---|
| `GOOGLE_PLACES_KEY` | your Google Places API key |
| `SMTP_HOST` | e.g. `smtp.zoho.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your outreach address |
| `SMTP_PASS` | its password or app password |
| `SMTP_FROM` | same as `SMTP_USER` |

Then the **Variables** tab (not Secrets):

| Variable | Value |
|---|---|
| `MARKET` | `uk`, `us` or `ae` |
| `AUTO_SEND` | leave unset for now — it drafts instead of sending |

### 3. Turn on Pages so the demo links work

Settings → **Pages** → Source: *Deploy from a branch* → branch `gh-pages`, folder `/`.

Your demos will be at `https://YOURNAME.github.io/agency-engine/`.
Put that in `config.yaml` as `demo_base_url` and push the change.

### 4. Let the Action write

Settings → **Actions → General → Workflow permissions** → *Read and write permissions*.

Without this it can't save the lead database between runs and it will find the
same businesses again every morning.

### 5. Test it before trusting it

Actions tab → **agency-engine** → *Run workflow* → stage `find`, market `uk`.

Watch it run. When it finishes, download the **leads-N** artifact at the bottom
and open `leads.csv`. That is your first batch.

## After that it runs itself

| Time (UTC) | What happens |
|---|---|
| 06:00 weekdays | finds new businesses, diagnoses them, builds demo sites, publishes them |
| 09:00 weekdays | emails the best leads — drafts only until you set `AUTO_SEND` |
| 17:00 weekdays | exports the CSV and the WhatsApp draft list |

Every run leaves a summary on the Actions page and a downloadable CSV.

## When you're ready to send for real

Read a week of drafts first. Rewrite `templates/msg/` in your own voice. Then
set the variable `AUTO_SEND` to `true`.

Start slow — put `emails_per_day: 10` in `config.yaml` for the first week, 25
the second, then raise it. A new sending domain that blasts 120 cold emails on
day one gets filtered permanently.

## Costs

GitHub Actions is free for 2,000 minutes a month on private repos. These runs
take about 3–5 minutes each, three times a weekday — roughly 300 minutes a
month. Comfortably inside the free tier.

The only thing you pay for is the Google Places API, and only when you use it.
Run with `--source osm` and it costs nothing at all.
