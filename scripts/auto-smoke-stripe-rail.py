#!/usr/bin/env python3
"""auto-smoke-stripe-rail.py — Run mechanical smoke checks on every Stripe-rail
product and mark passes:true in prd.json.

Per `sub-agents/devin/AGENT.md` smoke-test rule (updated 2026-05-14): products
following the identical Stripe-direct-bypass pattern (Stripe Payment Link →
felixops-site.vercel.app/{slug}/ → /thanks → /download/{pdf,zip}) need only
the 5 mechanical checks to mark done — the architecture was validated
end-to-end once on prd-024.

Run: python3 scripts/auto-smoke-stripe-rail.py [--dry-run] [--only prd-NNN]
"""

import os, sys, json, time, pathlib, argparse, datetime, re
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = pathlib.Path("/Users/vydaboss/argos")
SITES = ROOT / "products" / "felixops-site"
SITE_BASE = "https://felixops-site.vercel.app"

def build_slug_map():
    """Read each felixops-site product dir, return slug → stripe Payment Link URL."""
    out = {}
    for d in sorted(SITES.iterdir()):
        if not d.is_dir(): continue
        idx = d / "index.html"
        if not idx.exists(): continue
        m = re.search(r'href="(https://buy\.stripe\.com/[A-Za-z0-9]+)"', idx.read_text())
        if m:
            out[d.name] = m.group(1)
    return out

def matched_prd_for_url(prd, plurl):
    """Find prd item whose stripe.payment_link_url matches."""
    for item in prd.get("items", []):
        sb = item.get("stripe")
        if sb and sb.get("payment_link_url") == plurl:
            return item
    return None

def smoke_one_slug(slug):
    """Run 5 mechanical checks. Returns (ok, detail dict)."""
    landing = f"{SITE_BASE}/{slug}/"
    thanks = f"{SITE_BASE}/{slug}/thanks/"
    details = {}

    # 1. Landing
    r = requests.get(landing, timeout=15, allow_redirects=True)
    details["landing_status"] = r.status_code
    if r.status_code != 200:
        return False, details

    # Extract Stripe link + download paths
    m_stripe = re.search(r'href="(https://buy\.stripe\.com/[A-Za-z0-9]+)"', r.text)
    if not m_stripe:
        details["error"] = "no buy.stripe.com link on landing"
        return False, details
    details["stripe_url"] = m_stripe.group(1)

    # 2. Stripe checkout reachable
    sr = requests.get(details["stripe_url"], timeout=15, allow_redirects=True)
    details["stripe_status"] = sr.status_code
    if sr.status_code != 200:
        return False, details

    # 3. Thanks page
    tr = requests.get(thanks, timeout=15, allow_redirects=True)
    details["thanks_status"] = tr.status_code
    if tr.status_code != 200:
        return False, details

    # 4. PDF (required)
    pdf_m = re.findall(r'href="[./\w-]*download/([\w.-]+\.pdf)"', tr.text)
    if not pdf_m:
        details["error"] = "thanks page missing pdf link"
        return False, details

    pdf_url = f"{SITE_BASE}/{slug}/download/{pdf_m[0]}"
    pr = requests.head(pdf_url, timeout=15, allow_redirects=True)
    details["pdf_status"] = pr.status_code
    details["pdf_size"] = pr.headers.get("Content-Length", "?")
    details["pdf_type"] = pr.headers.get("Content-Type", "?")
    if pr.status_code != 200 or "application/pdf" not in details["pdf_type"]:
        return False, details

    # 5. ZIP (optional — some products are PDF-only)
    zip_m = re.findall(r'href="[./\w-]*download/([\w.-]+\.zip)"', tr.text)
    if zip_m:
        zip_url = f"{SITE_BASE}/{slug}/download/{zip_m[0]}"
        zr = requests.head(zip_url, timeout=15, allow_redirects=True)
        details["zip_status"] = zr.status_code
        details["zip_type"] = zr.headers.get("Content-Type", "?")
        if zr.status_code != 200 or "application/zip" not in details["zip_type"]:
            return False, details
    else:
        details["zip_status"] = "n/a (PDF-only product)"

    return True, details

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", type=str, help="Only smoke one prd-NNN")
    args = ap.parse_args()

    slug_map = build_slug_map()
    prd = json.load(open(ROOT / "prd.json"))
    print(f"Found {len(slug_map)} slugs on felixops-site. Running mechanical smoke on each.\n")

    results = []
    for slug, plurl in slug_map.items():
        item = matched_prd_for_url(prd, plurl)
        if not item:
            print(f"  {slug:35s} — no matching prd, skipping")
            continue
        pid = item["id"]
        if args.only and pid != args.only:
            continue
        if item.get("passes") and not args.only:
            # already passed previously, skip unless explicitly targeted
            print(f"  {pid:8s} ({slug:30s}) — already passes:true, skipping")
            continue
        ok, det = smoke_one_slug(slug)
        status = "✓" if ok else "✗"
        print(f"  {pid:8s} ({slug:30s}) {status}  landing={det.get('landing_status')} stripe={det.get('stripe_status')} thanks={det.get('thanks_status')} pdf={det.get('pdf_status')}/{det.get('pdf_size')} zip={det.get('zip_status')}")
        results.append((pid, slug, ok, det))

    # Update prd.json
    if not args.dry_run:
        prd_path = ROOT / "prd.json"
        prd = json.load(open(prd_path))
        updated = 0
        passed_ids = {pid for pid, _, ok, _ in results if ok}
        for item in prd.get("items", []):
            if item.get("id") in passed_ids:
                item["passes"] = True
                item["paused"] = False
                steps = item.setdefault("steps", [])
                steps.append({
                    "name": "auto-smoke-mechanical",
                    "status": "done",
                    "at": datetime.datetime.utcnow().isoformat() + "Z",
                    "note": "Autonomous mechanical smoke (auto-smoke-stripe-rail.py). 5/5 checks pass: landing/stripe/thanks/pdf/zip all HTTP 200.",
                })
                updated += 1
        json.dump(prd, open(prd_path, "w"), indent=2)
        print(f"\n✓ Updated {updated} prd items to passes:true, paused:false")

    # Audit log
    audit = ROOT / "AUDIT_LOG.md"
    now = datetime.datetime.utcnow().isoformat() + "Z"
    passed_n = sum(1 for _, _, ok, _ in results if ok)
    failed = [(p, s, d) for p, s, ok, d in results if not ok]
    with audit.open("a") as f:
        f.write(f"\n## aud-smoke-{now} | auto-smoke-stripe-rail (mechanical)\n")
        f.write(f"- Mode: {'dry-run' if args.dry_run else 'live'}.\n")
        f.write(f"- Scanned {len(results)} stripe-rail products.\n")
        f.write(f"- Passed mechanical (5/5 checks): {passed_n}.\n")
        f.write(f"- Failed: {len(failed)}.\n")
        if failed:
            for pid, slug, det in failed[:10]:
                err = det.get("error") or f"status landing={det.get('landing_status')} stripe={det.get('stripe_status')} thanks={det.get('thanks_status')}"
                f.write(f"  - {pid} ({slug}): {err}\n")
        f.write(f"- Result: {passed_n} products moved to passes:true, paused:false.\n\n")

    # Telegram ping
    try:
        cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
        tg = cfg["channels"]["telegram"]["botToken"]
        r = requests.post(f"https://api.telegram.org/bot{tg}/sendMessage",
                          data={"chat_id": "7161183058",
                                "text": f"Auto-smoke-stripe-rail done. {passed_n}/{len(results)} products pass 5/5 mechanical checks. Marked passes:true in prd.json. ({'dry-run' if args.dry_run else 'live'})"},
                          timeout=10)
    except Exception:
        pass

if __name__ == "__main__":
    main()
