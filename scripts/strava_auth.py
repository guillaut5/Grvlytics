"""One-shot OAuth2 flow to get a Strava refresh_token.

Usage:
    1. Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env
    2. Run: python scripts/strava_auth.py
    3. Open the printed URL, authorize, copy the `code` param from the
       redirect URL (the page will fail to load, that's expected - the
       code is in the browser address bar).
    4. Paste it back here. The refresh_token gets printed and appended
       to .env automatically.
"""
import os
import webbrowser
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv, set_key

load_dotenv()

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = "http://localhost"
SCOPE = "read,activity:read_all"

def main():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPE,
    }
    auth_url = f"https://www.strava.com/oauth/authorize?{urlencode(params)}"
    print(f"Ouvre cette URL, autorise l'appli, puis colle le `code` de l'URL de redirection:\n{auth_url}\n")
    webbrowser.open(auth_url)

    code = input("code=").strip()

    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    resp.raise_for_status()
    tokens = resp.json()

    set_key(".env", "STRAVA_REFRESH_TOKEN", tokens["refresh_token"])
    print("\nrefresh_token enregistré dans .env")
    print(f"athlete: {tokens['athlete']['firstname']} {tokens['athlete']['lastname']}")

if __name__ == "__main__":
    main()
