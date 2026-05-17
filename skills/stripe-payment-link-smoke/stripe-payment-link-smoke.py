#!/usr/bin/env python3
"""stripe-payment-link-smoke.py — Generic Stripe Payment Link funnel smoke test.

For each product in stripe-smoke.json, runs 5 HTTP checks:
  1. Landing page returns 200 + contains a buy.stripe.com link
  2. Stripe checkout URL returns 200
  3. Thanks page returns 200
  4. Thanks page contains a download link of expected extension
  5. Download URL returns 200 with the right content-type

Usage:
  python3 stripe-payment-link-smoke.py [--config PATH] [--only SLUG] [--strict] [--json]

Exit codes:
  0 — all products pass
  1 — at least one failure AND --strict was set
  2 — config missing / invalid
"""

import sys, json, re, argparse, pathlib
import requests

DEFAULT_CONFIG = "./stripe-smoke.json"

CONTENT_TYPE_MAP = {
    "pdf": "application/pdf",
    "zip": "application/zip",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
}


def smoke_one(product, site_base, timeout=15):
    """Run 5 mechanical checks. Returns (ok: bool, detail: dict)."""
    slug = product["slug"]
    landing_url = site_base.rstrip("/") + product["landing_url"]
    thanks_url = site_base.rstrip("/") + product["thanks_url"]
    extensions = product.get("download_extensions", ["pdf"])

    detail = {"slug": slug}

    # 1. Landing
    r = requests.get(landing_url, timeout=timeout, allow_redirects=True)
    detail["landing_status"] = r.status_code
    detail["landing_url"] = landing_url
    if r.status_code != 200:
        detail["error"] = f"landing returned {r.status_code}"
        return False, detail

    m_stripe = re.search(r'href="(https://buy\.stripe\.com/[A-Za-z0-9]+)"', r.text)
    if not m_stripe:
        detail["error"] = "no buy.stripe.com link found on landing page"
        return False, detail
    stripe_url = m_stripe.group(1)
    detail["stripe_url"] = stripe_url

    # 2. Stripe reachable
    sr = requests.get(stripe_url, timeout=timeout, allow_redirects=True)
    detail["stripe_status"] = sr.status_code
    if sr.status_code != 200:
        detail["error"] = f"stripe checkout returned {sr.status_code} (link archived?)"
        return False, detail

    # 3. Thanks page
    tr = requests.get(thanks_url, timeout=timeout, allow_redirects=True)
    detail["thanks_status"] = tr.status_code
    detail["thanks_url"] = thanks_url
    if tr.status_code != 200:
        detail["error"] = f"thanks page returned {tr.status_code}"
        return False, detail

    # 4. Download link present for each expected extension
    download_urls = {}
    for ext in extensions:
        pattern = r'href="([^"]*/download/[^"]+\.' + re.escape(ext) + r')"'
        m = re.search(pattern, tr.text)
        if not m:
            detail["error"] = f"thanks page missing .{ext} download link"
            return False, detail
        # Resolve relative URL
        href = m.group(1)
        if href.startswith("/"):
            href = site_base.rstrip("/") + href
        elif not href.startswith("http"):
            href = site_base.rstrip("/") + product["thanks_url"] + href
        download_urls[ext] = href

    detail["download_urls"] = download_urls

    # 5. Each download URL returns 200 + correct content-type
    for ext, dl_url in download_urls.items():
        dr = requests.head(dl_url, timeout=timeout, allow_redirects=True)
        detail[f"download_status_{ext}"] = dr.status_code
        if dr.status_code != 200:
            detail["error"] = f".{ext} download at {dl_url} returned {dr.status_code}"
            return False, detail
        expected_ct = CONTENT_TYPE_MAP.get(ext)
        actual_ct = dr.headers.get("content-type", "").split(";")[0].strip()
        detail[f"download_content_type_{ext}"] = actual_ct
        if expected_ct and not actual_ct.startswith(expected_ct):
            detail["error"] = f".{ext} returned content-type {actual_ct}, expected {expected_ct}"
            return False, detail

    return True, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--only", help="Only run this slug")
    ap.add_argument("--strict", action="store_true", help="Exit 1 on any failure (CI mode)")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of human-readable")
    args = ap.parse_args()

    cfg_path = pathlib.Path(args.config)
    if not cfg_path.exists():
        print(f"✗ Config not found: {cfg_path}", file=sys.stderr)
        print(f"  Copy {pathlib.Path(__file__).parent}/products.example.json to {cfg_path}", file=sys.stderr)
        sys.exit(2)

    cfg = json.load(cfg_path.open())
    site_base = cfg.get("site_base", "")
    if not site_base:
        print("✗ Config missing 'site_base'", file=sys.stderr)
        sys.exit(2)

    timeout = cfg.get("timeout_seconds", 15)
    products = cfg["products"]
    if args.only:
        products = [p for p in products if p["slug"] == args.only]
        if not products:
            print(f"✗ Slug '{args.only}' not in config", file=sys.stderr)
            sys.exit(2)

    results = []
    fails = 0
    for p in products:
        try:
            ok, detail = smoke_one(p, site_base, timeout)
        except Exception as e:
            ok, detail = False, {"slug": p["slug"], "error": f"exception: {e}"}
        results.append({"ok": ok, **detail})
        if not ok:
            fails += 1

    if args.json:
        print(json.dumps({"total": len(results), "fails": fails, "results": results}, indent=2))
    else:
        for r in results:
            mark = "✓" if r["ok"] else "✗"
            print(f"{mark} {r['slug']}")
            if not r["ok"]:
                print(f"    error: {r.get('error', 'unknown')}")
        print(f"\n{len(results)-fails}/{len(results)} passing")

    if fails > 0 and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
