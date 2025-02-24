import base64
import requests
from datetime import datetime, timedelta, timezone
from pyairtable import Api
import pytz
import os
import markdown
import re

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

PACIFIC_TIMEZONE = pytz.timezone("America/Los_Angeles")  # San Diego time
UTC_TIMEZONE = pytz.utc

api = Api(AIRTABLE_API_KEY)

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

# Convert Airtable Pacific Time to Cvent UTC
def convert_airtable_to_cvent_datetime(airtable_datetime):
    """Converts 'MM/DD/YYYY HH:MM AM/PM' (Pacific Time) to 'YYYY-MM-DDTHH:MM:SS.000Z' (UTC)"""
    try:
        dt_obj = datetime.strptime(airtable_datetime, "%m/%d/%Y %I:%M %p")
        dt_obj = PACIFIC_TIMEZONE.localize(dt_obj)  # Set as Pacific Time
        dt_obj = dt_obj.astimezone(UTC_TIMEZONE)  # Convert to UTC
        return dt_obj.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except ValueError:
        return None  # Return None if conversion fails

def get_modified_airtable_sessions():
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

    # Get current UTC time and subtract 1 hour
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fields to track for modifications
    field_list = [
        "Session Title (<100 characters)",
        "S25 Start Date/Time",
        "S25 End Date/Time",
        "Description (<2500 characters)",
        "W Room Text",  # Location (Plain Text)
        "Speaker Code (from Speaker)",  # Fetch speaker codes
        "Moderator Code",  # Fetch moderator codes
        "S Stage",
        "W Presentation Type Text",  # Type (Plain Text)
        "Website Tags (SELECT 3 MAX)"
    ]

    # Build filter formula correctly with field names wrapped in `{}` and use Airtable-compatible date format
    field_conditions = [f"LAST_MODIFIED_TIME({{{field}}}) > '{one_hour_ago}'" for field in field_list]
    formula = "OR(" + ", ".join(field_conditions) + ")"

    records = table.all(view=AIRTABLE_VIEW_ID, formula=formula)

    return {
        record["fields"]["Cvent Session ID"]: {
            "record_id": record["id"],
            "title": record["fields"].get("Session Title (<100 characters)", "").strip(),
            "start_time": convert_airtable_to_cvent_datetime(record["fields"].get("S25 Start Date/Time", "")),
            "end_time": convert_airtable_to_cvent_datetime(record["fields"].get("S25 End Date/Time", "")),
            "description": record["fields"].get("Description (<2500 characters)", "").strip(),
            "location": record["fields"].get("W Room Text", "").strip(),  # Using text field
            "speakers": [code.strip() for code in record["fields"].get("Speaker Code (from Speaker)", "") if code.strip()],  # Extract speakers
            "moderators": [code.strip() for code in record["fields"].get("Moderator code", "") if code.strip()],  # Extract moderators
            "stage": record["fields"].get("W Channel Text", "").strip(),
            "type": record["fields"].get("W Presentation Type Text", "").strip(),  # Using text field
            "tags": record["fields"].get("Website Tags (SELECT 3 MAX)", []) if isinstance(record["fields"].get("Website Tags (SELECT 3 MAX)"), list) else []
        }
        for record in records if "Cvent Session ID" in record["fields"]
    }



# Fetch existing Cvent session details
def get_cvent_session(session_id):
    """Fetches existing session details from Cvent to avoid missing required fields."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch session {session_id} details. Error: {response.text}")
        return None

# Fetch all session locations from Cvent
def get_cvent_session_locations():
    """Fetches all session locations from Cvent and returns a mapping of {Location Name: Location ID}."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/events/{CVENT_EVENT_ID}/session-locations?limit=100"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    locations = {}
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for loc in data.get("data", []):
                locations[loc["name"]] = loc["id"]  # Store {Location Name: Location ID}

            # Handle pagination
            next_token = data.get("paging", {}).get("nextToken")
            url = f"{CVENT_HOST}/{CVENT_VERSION}/events/{CVENT_EVENT_ID}/session-locations?limit=100&token={next_token}" if next_token else None
        else:
            print(f"Failed to fetch Cvent session locations. Error: {response.text}")
            break

    return locations

# Fetch Cvent session locations once before updating sessions
CVENT_SESSION_LOCATIONS = get_cvent_session_locations()

def get_cvent_speaker_categories():
    """Fetches all speaker categories and returns {Category Name: Category ID}."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/speaker-categories?limit=100"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    categories = {}
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for category in data.get("data", []):
                categories[category["name"].strip().lower()] = category["id"]  # Store {Category Name: Category ID}

            # Handle pagination
            next_token = data.get("paging", {}).get("nextToken")
            url = f"{CVENT_HOST}/{CVENT_VERSION}/speaker-categories?limit=100&token={next_token}" if next_token else None
        else:
            print(f"Failed to fetch Cvent speaker categories. Error: {response.text}")
            break

    return categories  # Returns {Category Name: Category ID}

CVENT_SPEAKER_CATEGORIES = get_cvent_speaker_categories()

def assign_speaker_to_session(session_id, speaker_id, category_id):
    """Assigns a speaker or moderator to a session with the correct category."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}/speakers/{speaker_id}"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    json_data = {
        "speakerCategory": {"id": category_id},  # Assign category
        "order": 1
    }

    response = requests.put(url, headers=headers, json=json_data)
    if 199 < response.status_code < 300:
        print(f"Assigned speaker {speaker_id} (Category ID: {category_id}) to session {session_id}.")
    else:
        print(f"Failed to assign speaker {speaker_id} to session {session_id}. Error: {response.text}")

def remove_speaker_from_session(session_id, speaker_id):
    """Removes a speaker from a session."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}/speakers/{speaker_id}"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    response = requests.delete(url, headers=headers)
    if 199 < response.status_code < 300:
        print(f"Removed speaker {speaker_id} from session {session_id}.")
    else:
        print(response)
        print(f"Failed to remove speaker {speaker_id} from session {session_id}. Error: {response.text}")

def get_cvent_session_speakers(session_id):
    """Fetches all speakers assigned to a session."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}/speakers?limit=100"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    speakers = {}
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for speaker in data.get("data", []):
                speakers[speaker["id"]] = speaker["category"]["id"]  # Store {Speaker ID: Category ID}

            # Handle pagination
            next_token = data.get("paging", {}).get("nextToken")
            url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}/speakers?limit=100&token={next_token}" if next_token else None
        else:
            print(f"Failed to fetch session speakers for {session_id}. Error: {response.text}")
            break

    return speakers  # Returns {Speaker ID: Category ID}


def get_cvent_speakers():
    """Fetches all available speakers for the event and returns {Speaker Code: Speaker ID}."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/speakers?filter=event.id eq '{CVENT_EVENT_ID}'&limit=100"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
    }

    speakers = {}
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for speaker in data.get("data", []):
                if "code" in speaker:
                    speakers[speaker["code"]] = speaker["id"]  # Store {Speaker Code: Speaker ID}

            # Handle pagination
            next_token = data.get("paging", {}).get("nextToken")
            url = f"{CVENT_HOST}/{CVENT_VERSION}/speakers?filter=event.id eq '{CVENT_EVENT_ID}'&limit=100&token={next_token}" if next_token else None
        else:
            print(f"Failed to fetch Cvent speakers. Error: {response.text}")
            break

    return speakers  # Returns {Speaker Code: Speaker ID}


def get_cvent_custom_fields():
    """Fetches all custom fields and returns a mapping of {Custom Field Name: Custom Field ID}."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/custom-fields?limit=100&filter=category eq 'Session'"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}"
    }

    custom_fields = {}
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for field in data.get("data", []):
                custom_fields[field["name"].strip().lower()] = field["id"]  # Store {Field Name: Field ID}

            # Handle pagination
            next_token = data.get("paging", {}).get("nextToken")
            url = f"{CVENT_HOST}/{CVENT_VERSION}/custom-fields?limit=100&token={next_token}" if next_token else None
        else:
            print(f"Failed to fetch Cvent custom fields. Error: {response.text}")
            break

    return custom_fields  # Returns {Custom Field Name: Custom Field ID}


def update_session_custom_field(session_id, custom_field_id, value):
    """Updates a custom field answer for a session."""
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}/custom-fields/{custom_field_id}/answers"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    json_data = {
        "id": custom_field_id,
        "value": value if isinstance(value, list) else [value]  # Convert to list if single value
    }

    response = requests.put(url, headers=headers, json=json_data)
    if response.status_code == 200:
        print(f"Updated custom field {custom_field_id} for session {session_id}.")
    else:
        print(f"Failed to update custom field {custom_field_id} for session {session_id}. Error: {response.text}")

AVAILABLE_SPEAKERS = get_cvent_speakers()

def update_session_speakers(session_id, airtable_speaker_codes, airtable_moderator_codes):
    """Syncs Airtable speakers & moderators with Cvent session speakers and updates categories if needed."""
    current_speakers = get_cvent_session_speakers(session_id)  # {Speaker ID: Category ID}

    # Get category IDs
    speaker_category_id = CVENT_SPEAKER_CATEGORIES.get("speaker")
    moderator_category_id = CVENT_SPEAKER_CATEGORIES.get("moderator")

    # Convert Airtable speaker codes to Cvent speaker IDs
    airtable_speaker_ids = {AVAILABLE_SPEAKERS[code]: speaker_category_id for code in airtable_speaker_codes if code in AVAILABLE_SPEAKERS}
    airtable_moderator_ids = {AVAILABLE_SPEAKERS[code]: moderator_category_id for code in airtable_moderator_codes if code in AVAILABLE_SPEAKERS}

    # Combine all assignments
    all_airtable_speakers = {**airtable_speaker_ids, **airtable_moderator_ids}

    # Determine speakers to remove (category changed or not in Airtable)
    to_remove = [
        speaker_id for speaker_id, current_category in current_speakers.items()
        if speaker_id not in all_airtable_speakers or all_airtable_speakers[speaker_id] != current_category
    ]

    # Determine speakers to add (newly assigned or category changed)
    to_add = {
        speaker_id: category_id
        for speaker_id, category_id in all_airtable_speakers.items()
        if speaker_id not in current_speakers or current_speakers[speaker_id] != category_id
    }

    # Remove speakers that have changed categories or are no longer assigned
    for speaker_id in to_remove:
        remove_speaker_from_session(session_id, speaker_id)

    # Assign missing speakers or reassign with updated category
    for speaker_id, category_id in to_add.items():
        assign_speaker_to_session(session_id, speaker_id, category_id)

CUSTOM_FIELDS = get_cvent_custom_fields()

def fix_bold_italic_syntax(text):
    """Fix incorrectly formatted bold/italic text by removing spaces inside the asterisks."""
    text = re.sub(r'\*\*(.*?)\s\*\*', r'**\1**', text)  # Fix bold
    text = re.sub(r'\*\*\*(.*?)\s\*\*\*', r'***\1***', text)  # Fix bold & italic
    text = re.sub(r'\*(.*?)\s\*', r'*\1*', text)  # Fix italic
    return text



def convert_markdown_to_html(markdown_text):
    """Converts Markdown to HTML while ensuring paragraphs are properly spaced."""
    if not markdown_text:
        return ""

    # Fix bold/italic formatting issues
    markdown_text = fix_bold_italic_syntax(markdown_text)

    # Remove leading spaces from each line
    markdown_text = re.sub(r'^\s+', '', markdown_text, flags=re.MULTILINE)

    # Ensure every new line creates a new paragraph
    markdown_text = re.sub(r'([^\n])\n([^\n])', r'\1\n\n\2', markdown_text)

    # Convert Markdown to HTML
    html = markdown.markdown(markdown_text, extensions=["extra"])

    # Add empty paragraphs between real paragraphs for extra spacing
    html = re.sub(r'</p>\s*<p>', '</p>\n<p></p>\n<p>', html)

    return html


def update_cvent_session(session_id, session_data):
    url = f"{CVENT_HOST}/{CVENT_VERSION}/sessions/{session_id}"
    headers = {
        "Authorization": f"Bearer {CVENT_ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Fetch existing session details to avoid missing required fields
    existing_session = get_cvent_session(session_id)

    if not existing_session:
        print(f"Skipping update for session {session_id} due to missing details.")
        return

    description_html = convert_markdown_to_html(session_data["description"])

    # Fetch custom field IDs
    custom_fields = get_cvent_custom_fields()

    # Sync both Speakers & Moderators
    update_session_speakers(session_id, session_data["speakers"], session_data["moderators"])

    # Ensure required fields are present
    json_data = {
        "status": existing_session.get("status", "ACTIVE"),  # Default to ACTIVE
        "event": {"id": CVENT_EVENT_ID},
        "title": session_data["title"] if session_data["title"] else existing_session.get("name"),
        "start": session_data["start_time"] if session_data["start_time"] else existing_session.get("start"),
        "end": session_data["end_time"] if session_data["end_time"] else existing_session.get("end"),
        "description": description_html,
        "location": {"id": CVENT_SESSION_LOCATIONS.get(session_data["location"])} if session_data["location"] else existing_session.get("location"),
    }

    # Remove empty values
    json_data = {k: v for k, v in json_data.items() if v}

    response = requests.put(url, headers=headers, json=json_data)

    if response.status_code == 200:
        print(f"Updated session {session_id} in Cvent.")
    else:
        print(f"Failed to update session {session_id}. Error: {response.text}")

    # Update custom fields
    if "stage" in session_data and session_data["stage"]:
        update_session_custom_field(session_id, custom_fields.get("stage"), session_data["stage"])

    if "type" in session_data and session_data["type"]:
        update_session_custom_field(session_id, custom_fields.get("type"), session_data["type"])

    if "tags" in session_data and session_data["tags"]:
        update_session_custom_field(session_id, custom_fields.get("tags"), session_data["tags"])

# Main function to check for updates every hour
def check_and_update_sessions():
    modified_sessions = get_modified_airtable_sessions()

    if not modified_sessions:
        print("No relevant session fields modified in the last hour.")
        return

    for session_id, session_data in modified_sessions.items():
        update_cvent_session(session_id, session_data)

# Run the script every hour
if __name__ == "__main__":
    check_and_update_sessions()
