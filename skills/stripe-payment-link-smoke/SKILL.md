---
name: stripe-payment-link-smoke
description: Pre-deploy funnel smoke test for any product that sells via a Stripe Payment Link. Verifies landing page → Stripe checkout → thanks page → digital-asset download in 5 mechanical HTTP checks per product. Catches "I deployed and didn't realize the download URL 404s" before customers hit it. Designed for solo founders shipping info products on Vercel / Netlify / Cloudflare Pages.
---

# stripe-payment-link-smoke

A pre-deploy smoke test for solo info-product founders running the Stripe Payment Link funnel pattern:

```
Landing page → Stripe Payment Link → Thanks page → Download (PDF / zip / video)
```

## When to invoke

- Before pushing a new product live to your site
- After ANY config change to a product's URLs, Stripe link, or download artifact
- Nightly cron — catches link-rot from your provider (Stripe Payment Link being archived, download artifact being moved)
- After moving providers (Vercel → Cloudflare Pages, etc.)

## Why this skill exists

The Stripe Payment Link funnel has 4 moving parts. Each part can break independently. When the funnel breaks mid-purchase, you lose:
- A customer's money (if Stripe fires but download fails — refund + apology)
- Trust (a 404 after paying looks like a scam to the buyer)
- Search ranking (if Google's crawler hits a 500 on your thanks page)

Manual testing every deploy is unreliable — most founders skip it after a few weeks. This skill runs 5 mechanical HTTP checks per product in ~10 seconds total:

1. **Landing page returns 200** and contains a `buy.stripe.com/...` link
2. **Stripe checkout URL returns 200** (link isn't archived, product still exists in Stripe)
3. **Thanks page returns 200** (post-purchase landing isn't broken)
4. **Thanks page links to a download URL** matching the expected pattern (PDF, zip, etc.)
5. **Download URL returns 200** and the right content-type (catches "I forgot to commit the PDF")

If all 5 pass: product is live and sellable. If any fail: detailed report on which step + what was missed.

## Setup

1. Copy `products.example.json` → your project's `stripe-smoke.json`
2. Fill in the list of products (slug + landing URL + expected artifact types)
3. Run locally: `python3 stripe-payment-link-smoke.py --config stripe-smoke.json`
4. Add to CI:
   ```yaml
   - name: Stripe funnel smoke
     run: python3 skills/stripe-payment-link-smoke/stripe-payment-link-smoke.py --strict
   ```
5. Optional: schedule nightly via cron / GitHub Actions to catch link rot

## Usage

```bash
# Local run, all products
python3 stripe-payment-link-smoke.py

# Specific product only
python3 stripe-payment-link-smoke.py --only my-product-slug

# CI mode (exit 1 on any failure)
python3 stripe-payment-link-smoke.py --strict

# Output JSON (for piping to a dashboard)
python3 stripe-payment-link-smoke.py --json
```

## What it does NOT do

- Does not actually purchase. The check stops at "Stripe checkout page loads" — it does not submit a card or trigger a webhook.
- Does not test webhook delivery from Stripe → your backend. Use Stripe's CLI for that.
- Does not check that the PDF you serve is the current version (just that something at the URL responds 200 + correct content-type).
- Does not check rate-limits / load-test. Single GET per URL.
- Does not auth into Stripe's API. Pure outside-in HTTP checks.

## Pricing rationale (for ClawMart listing)

$24 — bottom of the "useful CI tool" range. The category includes: pre-commit hook setups ($0-50 in time), uptime monitors ($10-30/mo subscription). This is a one-time purchase, runs locally, no SaaS dependency. Pays for itself the first time it catches a missing-PDF deploy.
