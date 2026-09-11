"""
Flip seo_addon_enabled = true on an audit by ID.

Uses the Supabase service role key from app1/.env so it works without
a browser session. Run from the app1/ directory:

    python flip_seo_flag.py <audit-id>

Example:
    python flip_seo_flag.py 52e27ced-3d14-448c-9fbf-822b2cb2197c
"""

import re
import sys
import urllib.request
import json


def main():
    if len(sys.argv) < 2:
        print("Usage: python flip_seo_flag.py <audit-id>")
        sys.exit(1)

    audit_id = sys.argv[1].strip()

    # Read Supabase creds from app1/.env
    env = open(".env").read()
    url = re.search(r"SUPABASE_URL=(.+)", env).group(1).strip()
    key = re.search(r"SUPABASE_SERVICE_ROLE_KEY=(.+)", env).group(1).strip()

    # PATCH the audit row
    data = json.dumps({"seo_addon_enabled": True}).encode()
    req = urllib.request.Request(
        f"{url}/rest/v1/geo_audits?id=eq.{audit_id}",
        data=data,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        method="PATCH",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if result:
            print(f"Done. seo_addon_enabled = {result[0].get('seo_addon_enabled')} on audit {audit_id}")
            print(f"Brand: {result[0].get('brand_name')}")
        else:
            print(f"No audit found with id {audit_id}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Failed ({e.code} {e.reason}): {body}")
        sys.exit(1)


if __name__ == "__main__":
    main()
