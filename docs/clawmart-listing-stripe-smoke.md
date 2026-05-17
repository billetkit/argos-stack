# ClawMart listing — stripe-payment-link-smoke

## Title (60 char max)

**Stripe Payment Link Funnel Smoke Test — pre-deploy check in 10s**

## Subtitle / one-liner (160 char max)

5 mechanical HTTP checks per product: landing page, Stripe link, thanks page, download URL, content-type. Catches missing-PDF deploys before customers do.

## Listing body

If you sell info products through Stripe Payment Links, this is the test you should already be running on every deploy.

The Stripe Payment Link funnel has 4 moving parts:

```
Landing page → Stripe Payment Link → Thanks page → Download (PDF / zip)
```

Each part can break independently. The expensive failures look like this:

- Stripe charge fires → buyer hits the thanks page → download URL is 404 → buyer demands refund + posts about your product on Twitter
- Your Stripe Payment Link gets archived in dashboard cleanup → landing page still links to it → 100% of new traffic hits a broken checkout for hours before you notice
- You move providers (Vercel → Cloudflare Pages) → all your download URLs change format → catch it in CI or catch it from a refund request

Manual testing every deploy is unreliable — most founders skip it after a few weeks. This is the 10-second mechanical version:

✓ Landing page returns 200 + contains a `buy.stripe.com/...` link
✓ Stripe checkout URL returns 200 (link isn't archived)
✓ Thanks page returns 200
✓ Thanks page contains the expected download links (PDF, zip, mp4, etc.)
✓ Each download URL returns 200 with the right content-type

All 5 in ~10 seconds per product. If anything fails, exact line-number report of what broke. JSON output mode for piping to a dashboard. `--strict` mode for CI fail-closed.

## What you get

- `stripe-payment-link-smoke.py` — single-file Python script, no external deps beyond `requests`
- `products.example.json` — copy and fill in your funnel URLs
- `SKILL.md` — usage docs + CI integration recipes
- Free updates for life

## What it does NOT do

- Does not actually purchase. Checks stop at "Stripe checkout page loads."
- Does not test webhook delivery. Use Stripe's CLI for that.
- Does not load-test or hit rate-limits.

## Who this is for

- Solo founders selling PDFs / zips / videos via Stripe Payment Links
- Anyone running the Felix Craft / Pieter Levels rail (landing → checkout → thanks → download)
- Indie hackers with 2+ products and growing fast enough to break funnels accidentally

## Quick start

```bash
# Copy example config
cp products.example.json my-products.json

# Edit with your product URLs
vim my-products.json

# Run
python3 stripe-payment-link-smoke.py --config my-products.json

# Or in CI (exit 1 on any failure)
python3 stripe-payment-link-smoke.py --strict
```

## Sample output

```
$ python3 stripe-payment-link-smoke.py
✓ how-to-hire-an-ai
✓ agent-starter-kit
✗ legacy-product
    error: stripe checkout returned 404 (link archived?)

2/3 passing
```

## Pricing

**$24 — one-time, lifetime updates**

Cheaper than:
- 1 missed-sale refund + apology email
- 1 hour of your time manually testing the funnel
- An uptime monitor subscription that doesn't even check Stripe link health

## Built by

[**billetkit**](https://billetkit.com) — solo dev shop shipping anti-marketplace tools for solo info-product founders. Free Stripe-rail kit + a $39 field guide on the realities of running an autonomous AI agent business at billetkit.com.

## Screenshots needed (TODO before listing)

1. Terminal output showing the 5 checks passing on a real funnel
2. Terminal output showing a clean failure with a specific error
3. JSON output mode rendered in a pretty viewer
4. CI integration screenshot (GitHub Actions log with the smoke test step)
5. The example `products.json` shown side-by-side with the actual URLs it tests

## Tags

stripe, payment-links, smoke-test, ci, pre-deploy, info-products, solo-founder, funnel, anti-rot, integration-test

## Pricing rationale notes

- ClawMart skill seller range: $10-$199 ([Composio 2026 top-10 skills](https://composio.dev/content/top-openclaw-skills))
- Similar tools (uptime checkers, post-deploy testers): $19-49 one-time or $9-29/month subscription
- $24 sits at the "cheap enough to impulse-buy, valuable enough to feel real" sweet spot
- First 10 buyers get $5 off via the billetkit.com PDF crossref code
