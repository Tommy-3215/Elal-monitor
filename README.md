# EL AL Seat Watcher ✈️ (cloud edition)

Watches **nonstop EL AL economy** flights from **TLV to five US gateways**
(JFK, EWR, BOS, MIA, LAX) and emails you when a seat **earlier than Tom's
current Aug 4 flight** appears — or when a known one gets **cheaper**. It runs
itself in the cloud, for free, on a schedule. Nothing runs on your computer or
your phone.

> **Why nonstop, why EL AL?** Tom is an unaccompanied minor and EL AL won't fly
> him on a connection, so any TLV→Austin routing (which requires stops) is out.
> The plan: get him nonstop to a US city on EL AL, where a parent meets him and
> they fly on to Austin together. So this watches the leg that has to work.

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

GitHub runs the check **every 3 hours** on its own servers (a free feature called
GitHub Actions). Each run:

1. searches every date in your window across all five gateways for **nonstop
   EL AL economy** (5 gateways × 14 dates = 70 searches),
2. keeps the best options per date+gateway (cheapest first),
3. emails you a short digest, grouped by gateway, **only if** something is new
   or cheaper,
4. remembers what it found (in `state/seen.json`) so it won't repeat itself.

> **Why every 3 hours and not hourly?** 70 searches per run is a lot; hourly
> would blow past the free Actions budget for a private repo. Every 3 hours is
> plenty for a flight change and stays comfortably free.

If you want to see it working, open the repo's **Actions** tab — every run shows
a green check, and you can press **Run workflow** to trigger one by hand.

---

## One-time setup (about 10 minutes, phone is fine)

Everything here can be done in a phone browser.

1. **This repo exists on GitHub** (you're reading its README, so ✅).
2. **Add three secrets.** This repo is public, so the email addresses live in
   secrets, not in the code. In **Settings → Secrets and variables → Actions →
   New repository secret**, add:
   - `SMTP_USER` — the sending Gmail address.
   - `EMAIL_TO` — comma-separated recipients (e.g. sender + a parent).
   - `SMTP_PASSWORD` — a Gmail *App Password* for the sending account, from
     [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
     (a 16-character code, not the real password). Once saved, nobody — not even
     you — can read a secret back.
   - *If the App Passwords page says it's unavailable,* turn on 2-Step
     Verification first (Google Account → Security), then try again.
3. **Turn on scheduled runs.** In the **Actions** tab, if it asks to enable
   workflows, click to enable. Press **Run workflow** once to test — you should
   get the first digest email within a minute or two.

That's it. It'll keep checking every 3 hours until you stop it.

---

## Changing what it watches

Open [`.github/workflows/watch.yml`](.github/workflows/watch.yml) and edit the
values under `env:` — dates, max stops, price ceiling, who gets the email. You
can edit it right in the GitHub web editor (pencil icon); saving is all it takes.

| Setting | Meaning |
|---|---|
| `DESTINATIONS` | Comma-separated US gateways to watch (e.g. `JFK,EWR,BOS,MIA,LAX`). |
| `DATE_START` / `DATE_END` | The window of departure dates to search. |
| `CURRENT_DEPARTURE_DATE` | The flight you're trying to beat (Aug 4). |
| `MAX_STOPS` | `0` = nonstop only. Keep it 0 while Tom flies as a minor. |
| `REQUIRE_ELAL` | `true` = EL AL-operated only. Set `false` to include other nonstop carriers (United, American, Delta) if you'd consider rebooking off EL AL. |
| `MAX_PRICE` | Optional ceiling; uncomment to ignore pricier options. |
| `PRICE_DROP_THRESHOLD` | Only re-alert on a drop of at least this many dollars. |
| `EMAIL_TO` | Comma-separated recipients. |
| `cron: "0 */3 * * *"` | How often to check. `*/3` = every 3 hours. |

To stop it: **Actions** tab → *EL AL seat watcher* → **⋯ → Disable workflow**.

---

## Honest limitations

- **Data comes from Google Flights, not EL AL directly.** It's an excellent,
  continuously-updated mirror of what's bookable, but a seat showing up there
  doesn't guarantee EL AL will rebook *Tom's ticket* onto it — the tool's job is
  to tell you *when to go check / call*, fast. It never books.
- **How it detects an economy seat (important).** Right now economy is sold out
  on these flights, so Google Flights hands back the **business** fare (~$6k)
  even when you search economy — and the data has no cabin label to read. But a
  real economy seat prices **~$1–3k**, far below business. So the watcher uses a
  **price ceiling** (`MAX_PRICE`, default $3,500): it ignores the ~$6k
  business-only fallbacks and stays silent, and alerts the moment a flight shows
  an economy-priced fare — i.e. someone freed up an economy seat. It's an
  inference from price, not a direct read of seat inventory, but the gap is wide
  and clean. **No email = economy still sold out** (the Actions tab still shows
  green runs, so you know it's alive).
- **BOS and LAX are thin.** EL AL flies them less often than JFK/EWR/MIA, so
  they'll alert rarely. They're kept in just in case.
- **Confirm EL AL's unaccompanied-minor rules** (age, fees, forms, cutoff
  times) when you book — the tool can't see those.
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
