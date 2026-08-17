"""
Discord -> Google Sheets poller
---------------------------------
Ports the pollDiscordMessages() logic from the Apps Script version.
Runs once per invocation - meant to be triggered on a schedule (e.g. Render Cron Job).

Required environment variables (set these in your host's dashboard, never hardcode):
  DISCORD_BOT_TOKEN       - your bot's token
  DISCORD_CHANNEL_ID      - the channel to poll
  GOOGLE_SHEET_ID         - the spreadsheet ID (from its URL)
  GOOGLE_SHEET_TAB        - the tab/sheet name, e.g. "Sheet1"
  GOOGLE_SERVICE_ACCOUNT_JSON - the FULL contents of your service account key file, as a single-line JSON string

Required Python packages (see requirements.txt):
  requests
  gspread
  google-auth
"""

import os
import json
import sys
from datetime import datetime, timezone

import requests
import gspread
from google.oauth2.service_account import Credentials

# ---- Config from environment ----
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CHANNEL_ID = os.environ["DISCORD_CHANNEL_ID"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SHEET_TAB = os.environ.get("GOOGLE_SHEET_TAB", "Sheet1")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# We use a dedicated hidden cell on the sheet to persist "last seen message ID"
# across runs, since this script has no memory between invocations (unlike
# Apps Script's PropertiesService). We stash it in a cell far off to the side
# so it doesn't interfere with the visible log. Change if you'd rather use a
# separate tiny "state" tab instead.
STATE_CELL = "Z1"


def get_sheet():
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    return spreadsheet.worksheet(GOOGLE_SHEET_TAB)


def get_last_message_id(sheet):
    value = sheet.acell(STATE_CELL).value
    return value if value else None


def set_last_message_id(sheet, message_id):
    sheet.update_acell(STATE_CELL, message_id)


def fetch_new_messages(after_id):
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    params = {"limit": 50}
    if after_id:
        params["after"] = after_id

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "User-Agent": "DiscordBot (https://github.com/your-repo, 1.0)",
    }

    response = requests.get(url, headers=headers, params=params, timeout=15)

    if response.status_code != 200:
        print(f"Discord API error: {response.status_code} - {response.text}", file=sys.stderr)
        return None

    return response.json()


def main():
    sheet = get_sheet()
    last_id = get_last_message_id(sheet)

    messages = fetch_new_messages(last_id)
    if messages is None:
        print("Poll failed, exiting without changes.")
        sys.exit(1)

    if not messages:
        print("No new messages.")
        return

    # Discord returns newest-first; reverse so we append oldest-first
    messages.reverse()

    rows_to_append = []
    for msg in messages:
        # Skip webhook-sent messages (these are our own outgoing sends echoing back)
        if msg.get("webhook_id"):
            continue

        timestamp_raw = msg["timestamp"]  # ISO 8601, e.g. "2026-08-17T16:20:30.123000+00:00"
        dt = datetime.fromisoformat(timestamp_raw)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        username = msg.get("author", {}).get("username", "Unknown")
        content = msg.get("content") or "(no text content - possibly an embed/attachment)"

        rows_to_append.append([timestamp_str, username, content, "IN"])

    if rows_to_append:
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print(f"Appended {len(rows_to_append)} new message(s).")
    else:
        print("No new non-webhook messages to append.")

    newest_id = messages[-1]["id"]
    set_last_message_id(sheet, newest_id)


if __name__ == "__main__":
    main()
