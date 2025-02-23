import base64
import requests
from collections import Counter
from datetime import datetime
from pyairtable import Api
import pytz
import os

# Cvent API Credentials
CVENT_HOST = "https://api-platform.cvent.com"
CVENT_VERSION = "ea"
CVENT_CLIENT_ID = os.environ.get("CVENT_CLIENT_ID")
CVENT_CLIENT_SECRET = os.environ.get("CVENT_CLIENT_SECRET")
CVENT_EVENT_ID = os.environ.get("CVENT_EVENT_ID")

# Airtable API Credentials
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME")
AIRTABLE_VIEW_ID = os.environ.get("AIRTABLE_VIEW_ID")

CVENT_TIMEZONE = pytz.utc
AIRTABLE_TIMEZONE = pytz.timezone("America/Los_Angeles")

# Authenticate with Cvent API (OAuth2 Client Credentials Flow)
def get_cvent_access_token():
    url = f"{CVENT_HOST}/{CVENT_VERSION}/oauth2/token"

    credentials = f"{CVENT_CLIENT_ID}:{CVENT_CLIENT_SECRET}"
    base64_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {base64_credentials}",
    }

    data = {"grant_type": "client_credentials", "client_id": CVENT_CLIENT_ID}

    response = requests.post(url, data=data, headers=headers)
    response.raise_for_status()

    return response.json().get("access_token")

CVENT_ACCESS_TOKEN = get_cvent_access_token()

# Convert Cvent datetime to Airtable format
def convert_cvent_to_airtable_format(cvent_datetime):
    """Converts 'YYYY-MM-DDTHH:MM:SS.SSSZ' (UTC) to 'MM/DD/YYYY HH:MM AM/PM' (Pacific Time)"""
    try:
        # Convert string to UTC datetime object
        dt_obj = datetime.strptime(cvent_datetime, "%Y-%m-%dT%H:%M:%S.%fZ")
        dt_obj = CVENT_TIMEZONE.localize(dt_obj)  # Set as UTC
        dt_obj = dt_obj.astimezone(AIRTABLE_TIMEZONE)  # Convert to Pacific Time

        # Format to match Airtable's datetime format
        return dt_obj.strftime("%m/%d/%Y %I:%M %p")  # Example: "04/08/2025 09:00 PM"
    except ValueError:
        return cvent_datetime  # If parsing fails, return original

# Fetch all sessions from Cvent
def get_cvent_sessions():
    sessions = []
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions?limit=100&filter=event.id eq '{CVENT_EVENT_ID}'"

    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        sessions.extend(data.get("data", []))

        next_token = data.get("paging", {}).get("nextToken")
        if next_token:
            url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions?limit=100&token={next_token}"
        else:
            url = None  # Stop pagination if no more pages

    # Store Cvent session data in a dictionary
    cvent_data = {}
    for session in sessions:
        session_title = session["title"]
        start_time = convert_cvent_to_airtable_format(session["start"])  # Convert format
        cvent_data.setdefault(session_title, {})[start_time] = session["id"]

    return cvent_data

# Convert Cvent datetime format to match Airtable
def convert_datetime_format(cvent_datetime):
    """Converts Cvent datetime format to Airtable format (if needed)"""
    try:
        dt_obj = datetime.strptime(cvent_datetime, "%Y-%m-%dT%H:%M:%SZ")
        return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return cvent_datetime  # If parsing fails, return original

# Fetch all sessions from Airtable
def get_airtable_sessions():
    api = Api(AIRTABLE_API_KEY)
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

    records = table.all(view=AIRTABLE_VIEW_ID)
    session_counts = Counter(record["fields"]["Session Title (<100 characters)"] for record in records if "Session Title (<100 characters)" in record["fields"])

    return {
        record["id"]: {
            "title": record["fields"]["Session Title (<100 characters)"],
            "start_time": record["fields"].get("S25 Start Date/Time", ""),
            "is_duplicate": session_counts[record["fields"]["Session Title (<100 characters)"]] > 1
        }
        for record in records if "Session Title (<100 characters)" in record["fields"]
    }

# Update session ID in Airtable
def update_airtable_session_code(record_id, session_id):
    api = Api(AIRTABLE_API_KEY)
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

    table.update(record_id, {"Session ID": session_id})

# Main logic to match and update sessions
def assign_codes_to_sessions():
    cvent_sessions = get_cvent_sessions()
    airtable_sessions = get_airtable_sessions()

    for record_id, session_info in airtable_sessions.items():
        session_name = session_info["title"]
        start_time = convert_datetime_format(session_info["start_time"])
        is_duplicate = session_info["is_duplicate"]

        if session_name in cvent_sessions:
            if is_duplicate and start_time in cvent_sessions[session_name]:
                # If the title is duplicated in Airtable, match using both title & start time
                session_id = cvent_sessions[session_name][start_time]
            else:
                # If the title is unique, match only using the title
                session_id = next(iter(cvent_sessions[session_name].values()))

            update_airtable_session_code(record_id, session_id)
            print(f"Updated session '{session_name}' ({start_time}) with ID {session_id}")
        else:
            print(f"No match found for session '{session_name}' ({start_time})")


if __name__ == "__main__":
    # Run the script
    assign_codes_to_sessions()
