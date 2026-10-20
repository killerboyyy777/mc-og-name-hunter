#!/usr/bin/env python3
"""Get a Minecraft access token with zero Azure app registration.

Uses mcauth3's built-in public client ID (device-code flow):
    Microsoft -> Xbox Live -> XSTS -> Minecraft services

Two-step so the code can be shown before the long poll:

    python get_token.py --new     # prints URL + code, saves device.json
    python get_token.py --poll    # waits for you to finish, then saves token

With a cached refresh token, plain `python get_token.py` refreshes silently.
"""

import argparse
import json
import sys
from pathlib import Path

from mcauth3 import MCMSA, OAuthError

BASE = Path(__file__).parent
CACHE_FILE = BASE / "data" / "mcauth.json"
TOKEN_FILE = BASE / "data" / "mojang_token.txt"
DEVICE_FILE = BASE / "data" / "mcauth_device.json"


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def report(tokens: dict, profile: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps({"tokens": tokens, "profile": profile}, indent=2),
        encoding="utf-8",
    )
    TOKEN_FILE.write_text(tokens["minecraft_access_token"], encoding="utf-8")
    print("\nSUCCESS")
    print(f"  Player   : {profile.get('name')} ({profile.get('id')})")
    print(f"  Expires  : {tokens.get('expires_in')}s")
    print(f"  Cached to: {CACHE_FILE}")
    print(f"  Token to : {TOKEN_FILE}")
    print("\nThe sniper reads the cached token automatically.")
    print("To export it manually (PowerShell):")
    print(f'  $env:MOJANG_ACCESS_TOKEN = (Get-Content "{TOKEN_FILE}" -Raw).Trim()')


def do_new(auth: MCMSA):
    device = auth.start_auth()
    DEVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_FILE.write_text(json.dumps(device), encoding="utf-8")
    print("=== Microsoft device login ===")
    print(f"1. Open : {device['verification_uri']}")
    print(f"2. Enter: {device['user_code']}")
    print(f"(expires in {device['expires_in']}s)")
    print("\nThen run: python get_token.py --poll")


def do_poll(auth: MCMSA):
    device = load_json(DEVICE_FILE)
    if not device:
        print("No device code saved. Run: python get_token.py --new")
        sys.exit(1)
    print("Waiting for login...")
    sys.stdout.flush()
    result = auth.finish_auth(device)
    DEVICE_FILE.unlink(missing_ok=True)
    report(result["tokens"], result["profile"])


def do_auto(auth: MCMSA):
    cache = load_json(CACHE_FILE)
    refresh_token = (cache.get("tokens") or {}).get("microsoft_refresh_token")
    if refresh_token:
        print("[INFO] Refreshing cached Microsoft token...")
        try:
            result = auth.refresh_auth(refresh_token)
            report(result["tokens"], result["profile"])
            return
        except OAuthError as exc:
            print(f"[WARN] Refresh failed ({exc}); starting new device login.")
    do_new(auth)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--new", action="store_true", help="start a new device login")
    group.add_argument("--poll", action="store_true", help="finish a pending device login")
    args = parser.parse_args()

    auth = MCMSA()
    if args.new:
        do_new(auth)
    elif args.poll:
        do_poll(auth)
    else:
        do_auto(auth)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)