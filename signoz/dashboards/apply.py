#!/usr/bin/env python3
"""Upsert the SigNoz dashboards in this directory via the SigNoz API.

Dashboards are matched by title: an existing dashboard with the same title is
replaced in place (its id and URL stay), otherwise it is created. Nothing is
ever deleted. The JSON files are the dashboard "data" object as the SigNoz UI
exports it (version v5 query builder, SigNoz >= 0.120).

Usage:
    SIGNOZ_URL=https://signoz.example.com SIGNOZ_API_KEY=... ./apply.py [--dry-run] [FILE...]

Only the Python standard library is used, so this runs on the hubcap host as is.
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
    p.add_argument("files", nargs="*", help="dashboard JSON files (default: every *.json next to this script)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    base = os.environ.get("SIGNOZ_URL", "").rstrip("/")
    key = os.environ.get("SIGNOZ_API_KEY", "")
    if not args.dry_run and (not base or not key):
        sys.exit("set SIGNOZ_URL and SIGNOZ_API_KEY (an API key / service-account key with the editor or admin role)")

    files = args.files or sorted(glob.glob(os.path.join(HERE, "*.json")))
    if not files:
        sys.exit("no dashboard files found")

    existing = {}
    if base and key:
        for d in api("GET", f"{base}/api/v1/dashboards", key)["data"]:
            existing[d["data"]["title"]] = d["id"]

    for path in files:
        with open(path) as f:
            dashboard = json.load(f)
        title = dashboard["title"]
        if args.dry_run:
            print(f"[dry-run] {'update' if title in existing else 'create'}: {title}  ({len(dashboard['widgets'])} panels)")
            continue
        if title in existing:
            api("PUT", f"{base}/api/v1/dashboards/{existing[title]}", key, dashboard)
            print(f"updated: {title}  {base}/dashboard/{existing[title]}")
        else:
            created = api("POST", f"{base}/api/v1/dashboards", key, dashboard)
            print(f"created: {title}  {base}/dashboard/{created['data']['id']}")


if __name__ == "__main__":
    main()
