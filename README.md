# EL AL Seat Watcher ✈️ (cloud edition)

Watches **TLV → AUS economy** availability and emails you when an option that's
**earlier than your current Aug 4 flight** appears — or when a known option gets
**cheaper**. It runs itself in the cloud, for free, on a schedule. Nothing runs
on your computer or your phone.

> **Notify-only.** It never books, pays, or logs in anywhere. It just tells you
> when to go look.

---

## Built on Tom's work 🙌

Tom built the original version of this tool. The engine here is his design:

- the **alert rules** (economy only, earlier than your current flight, EL AL
  ranked first, never alert twice) — his;
- the **de-duplication memory** so the same flight doesn't nag you — his idea,
  now also remembering prices so it can spot price drops;
- the **email notifier** (multi-recipient, and Discord/Telegram if you ever want
  them) — his code, unchanged.

The **one** thing that changed is where the flight data comes from. Tom's version
scraped elal.com with a real browser, which he correctly flagged as the fragile
part — airline sites fight automation hard. This version asks **Google Flights**
for the same information over a normal web request: no browser, no CAPTCHA, no
login. That's what makes it dependable enough to run unattended.

---

## How it runs (the important part)

GitHub runs the check **every 2 hours** on its own servers (a free feature called
GitHub Actions). Each run:

1. searches every date in your window for TLV → AUS economy,
2. keeps the best few options per date (EL AL first, then cheapest),
3. emails you a short digest **only if** something is new or cheaper,
4. remembers what it found (in `state/seen.json`) so it won't repeat itself.

If you want to see it working, open the repo's **Actions** tab — every run shows
a green check, and you can press **Run workflow** to trigger one by hand.

---

## One-time setup (about 10 minutes, phone is fine)

Everything here can be done in a phone browser.

1. **This repo exists on GitHub** (you're reading its README, so ✅).
2. **Add the email password as a secret.** Make a Gmail *App Password* for the
   sending account (`ozertom@gmail.com`) at
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   — it's a 16-character code, not the real password. Then in this repo go to
   **Settings → Secrets and variables → Actions → New repository secret**, name
   it exactly `SMTP_PASSWORD`, paste the code, and save. That's the only secret,
   and once saved nobody (not even you) can read it back.
   - *If the App Passwords page says it's unavailable,* turn on 2-Step
     Verification first (Google Account → Security), then try again.
3. **Turn on scheduled runs.** In the **Actions** tab, if it asks to enable
   workflows, click to enable. Press **Run workflow** once to test — you should
   get the first digest email within a minute or two.

That's it. It'll keep checking every 2 hours until you stop it.

---

## Changing what it watches

Open [`.github/workflows/watch.yml`](.github/workflows/watch.yml) and edit the
values under `env:` — dates, max stops, price ceiling, who gets the email. You
can edit it right in the GitHub web editor (pencil icon); saving is all it takes.

| Setting | Meaning |
|---|---|
| `DATE_START` / `DATE_END` | The window of departure dates to search. |
| `CURRENT_DEPARTURE_DATE` | The flight you're trying to beat (Aug 4). |
| `MAX_STOPS` | Ignore itineraries with more stops (0 = nonstop only). |
| `MAX_PRICE` | Optional ceiling; uncomment to ignore pricier options. |
| `TOP_PER_DATE` | How many options per date to consider (keeps email short). |
| `PRICE_DROP_THRESHOLD` | Only re-alert on a drop of at least this many dollars. |
| `EMAIL_TO` | Comma-separated recipients. |
| `cron: "0 */2 * * *"` | How often to check. `*/2` = every 2 hours. |

To stop it: **Actions** tab → *EL AL seat watcher* → **⋯ → Disable workflow**.

---

## Honest limitations

- **Data comes from Google Flights, not EL AL directly.** It's an excellent,
  continuously-updated mirror of what's bookable, but a seat showing up there
  doesn't guarantee EL AL will rebook *your ticket* onto it — the tool's job is
  to tell you *when to go check / call*, fast. It never books.
- **TLV → AUS has no nonstop**, so expect 1–2 stop itineraries (often EL AL to
  the US East Coast, then a partner airline onward).
- **If the data source ever changes** and a run can't fetch anything, the tool
  emails you an "all searches failed" heads-up instead of going silently dark.

---

## Running it on your own computer (optional)

You don't need to — the cloud handles it — but to test locally:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your App Password in .env
python -m src.monitor --dry-run     # searches + prints the digest, sends nothing
python -m src.monitor --notify-test # sends one test email
python -m src.monitor               # one real run
```

## Project layout

```
elal-monitor-cloud/
├── .github/workflows/watch.yml  # the cloud scheduler
├── src/
│   ├── config.py       # settings from env (Tom's, minus the browser bits)
│   ├── models.py       # a flight option + its fingerprint (adapted from Tom's)
│   ├── search.py       # NEW: Google Flights lookup (replaces his scraper.py)
│   ├── store.py        # de-dup + price memory (extends Tom's)
│   ├── notifier.py     # email / Discord / Telegram  (Tom's, unchanged)
│   ├── logging_setup.py# logging (Tom's, unchanged)
│   └── monitor.py      # ties it together: search → filter → alert
├── state/seen.json     # the watcher's memory (created + committed automatically)
├── requirements.txt
└── .env.example
```
