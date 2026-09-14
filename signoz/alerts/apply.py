#!/usr/bin/env python3
"""Upsert the SigNoz alert rules in this directory via the SigNoz API.

Rules are matched by their "alert" name: an existing rule with the same name
is updated in place, otherwise it is created. Nothing is ever deleted.

Usage:
    SIGNOZ_URL=https://signoz.example.com SIGNOZ_API_KEY=... ./apply.py [--dry-run] [--channel NAME] [FILE...]

    --channel NAME   send alerts to the SigNoz notification channel NAME
                     instead of the name written in the JSON (default: discord-alerts)
    --dry-run        print what would change without calling the API

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


def set_channel(rule, channel):
    for threshold in rule["condition"]["thresholds"]["spec"]:
        threshold["channels"] = [channel]
    return rule


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", help="rule JSON files (default: every *.json next to this script)")
    p.add_argument("--channel", help="notification channel name to route every threshold to")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    base = os.environ.get("SIGNOZ_URL", "").rstrip("/")
    key = os.environ.get("SIGNOZ_API_KEY", "")
    if not args.dry_run and (not base or not key):
        sys.exit("set SIGNOZ_URL and SIGNOZ_API_KEY (Settings → API Keys, role Admin)")

    files = args.files or sorted(glob.glob(os.path.join(HERE, "*.json")))
    if not files:
        sys.exit("no rule files found")

    existing = {}
    if not args.dry_run:
        for r in api("GET", f"{base}/api/v1/rules", key)["data"]["rules"]:
            existing[r["alert"]] = r["id"]

    for path in files:
        with open(path) as f:
            rule = json.load(f)
        if args.channel:
            set_channel(rule, args.channel)
        name = rule["alert"]
        channels = sorted({c for t in rule["condition"]["thresholds"]["spec"] for c in t["channels"]})
        if args.dry_run:
            action = "update" if name in existing else "create"
            print(f"[dry-run] {action}: {name}  (channels: {', '.join(channels)})")
            continue
        if name in existing:
            api("PUT", f"{base}/api/v1/rules/{existing[name]}", key, rule)
            print(f"updated: {name}")
        else:
            api("POST", f"{base}/api/v1/rules", key, rule)
            print(f"created: {name}")


if __name__ == "__main__":
    main()
