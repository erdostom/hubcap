#!/usr/bin/env python3
"""Upsert the SigNoz explorer saved views in this directory via the SigNoz API.

Views are matched by name: an existing view with the same name is updated in
place, otherwise it is created. Nothing is ever deleted. Saved views show up
in the Logs / Traces explorers' "Views" menu and on the SigNoz Home page.

Usage:
    SIGNOZ_URL=https://signoz.example.com SIGNOZ_API_KEY=... ./apply.py [--dry-run] [FILE...]
"""

import argparse
import glob
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def api(method, url, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("SIGNOZ-API-KEY", key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {url} failed: HTTP {e.code}: {e.read().decode(errors='replace')}")
    return json.loads(payload) if payload else {}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", help="view JSON files (default: every *.json next to this script)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    base = os.environ.get("SIGNOZ_URL", "").rstrip("/")
    key = os.environ.get("SIGNOZ_API_KEY", "")
    if not args.dry_run and (not base or not key):
        sys.exit("set SIGNOZ_URL and SIGNOZ_API_KEY (an API key / service-account key with the editor or admin role)")

    files = args.files or sorted(glob.glob(os.path.join(HERE, "*.json")))
    if not files:
        sys.exit("no view files found")

    existing = {}
    if base and key:
        # The list endpoint returns nothing without a sourcePage filter.
        for page in ("logs", "traces"):
            for v in api("GET", f"{base}/api/v1/explorer/views?sourcePage={page}", key).get("data") or []:
                existing[v["name"]] = v["id"]

    for path in files:
        with open(path) as f:
            view = json.load(f)
        name = view["name"]
        if args.dry_run:
            print(f"[dry-run] {'update' if name in existing else 'create'}: {name}  ({view['sourcePage']})")
            continue
        if name in existing:
            api("PUT", f"{base}/api/v1/explorer/views/{existing[name]}", key, view)
            print(f"updated: {name}")
        else:
            api("POST", f"{base}/api/v1/explorer/views", key, view)
            print(f"created: {name}")


if __name__ == "__main__":
    main()
