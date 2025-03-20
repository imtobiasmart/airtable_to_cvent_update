import os
import sys
import time
from datetime import datetime, timedelta
from pyairtable import Api

# Configure logging for GitHub Actions environment
def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    # Add GitHub Actions workflow commands for better visibility
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if "ERROR" in message:
            print(f"::error::{message}")
        elif "WARNING" in message:
            print(f"::warning::{message}")

def process_airtable_data():
    log("=== Airtable Speaker Session Migration Tool ===")

    # Get credentials from environment variables
    api_key = os.environ.get("AIRTABLE_API_KEY")
    if not api_key:
        log("ERROR: AIRTABLE_API_KEY environment variable is not set")
        sys.exit(1)

    base_id = os.environ.get("AIRTABLE_BASE_ID", "appjjd9bJVKNuUTyL")
    source_table_id = os.environ.get("AIRTABLE_SOURCE_TABLE", "tblAD4ax7xst4inyC")
    dest_table_id = os.environ.get("AIRTABLE_DEST_TABLE", "tblZRPk0Y3NydRuZz")
    view_name = os.environ.get("AIRTABLE_VIEW_NAME", "S25 Speakers_EA View")

    # Get last sync timestamp from environment variable or use a default (24 hours ago)
    last_sync_time = os.environ.get("LAST_SYNC_TIME")
    if not last_sync_time:
        # Default to 24 hours ago
        last_sync_time = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    log(f"Processing records modified since: {last_sync_time}")

    try:
        # Initialize the API and get tables
        api = Api(api_key)
        source_table = api.table(base_id, source_table_id)
        dest_table = api.table(base_id, dest_table_id)

        # Fetch records from the specified view that were modified since last sync
        log(f"Fetching records from Speaker table with '{view_name}' view...")
        formula = f"LAST_MODIFIED_TIME() >= '{last_sync_time}'"
        records = source_table.all(view=view_name, formula=formula)
        log(f"Found {len(records)} speaker records modified since last sync")

        if not records:
            log("No records to process. Exiting.")
            # Set the output for GitHub Actions
            if os.environ.get("GITHUB_ACTIONS") == "true":
                with open(os.environ.get("GITHUB_OUTPUT", ""), "a") as f:
                    f.write(f"last_sync_time={datetime.now().strftime('%Y-%m-%dT%H:%M:%S.000Z')}\n")
            return

        # Get existing records from destination table for possible updates
        log("Fetching existing records from destination table...")
        existing_records = dest_table.all()
        log(f"Found {len(existing_records)} existing records in destination table")

        # Create lookup dictionary for faster matching
        existing_record_map = {}
        for er in existing_records:
            er_fields = er.get('fields', {})
            speaker_id = er_fields.get('Speaker', [''])[0] if er_fields.get('Speaker') else ''
            session_id = er_fields.get('Session', [''])[0] if er_fields.get('Session') else ''
            role = er_fields.get('Role', '')

            if speaker_id and session_id and role:
                key = f"{speaker_id}_{session_id}_{role}"
                existing_record_map[key] = er['id']

        # Lists to track operations
        records_to_create = []
        records_to_update = []
        processed_records = set()

        # Process each speaker record
        for record in records:
            record_id = record['id']
            fields = record['fields']
            speaker_name = fields.get('Name', '')
            s_channel = fields.get('S Channel', [])

            # Process sessions where the speaker is speaking
            speaking_sessions = fields.get('Speaking', [])
            if speaking_sessions:
                # Ensure speaking_sessions is a list
                if not isinstance(speaking_sessions, list):
                    speaking_sessions = [speaking_sessions]

                # Create a record for each speaking session
                for session_id in speaking_sessions:
                    session_fields = {
                        'Name': speaker_name,
                        'Speaker': [record_id],
                        'Session': [session_id],
                        'Role': 'Speaking',
                        'S Channel': s_channel
                    }

                    # Check if this record already exists
                    key = f"{record_id}_{session_id}_Speaking"
                    if key in existing_record_map:
                        # Record exists, prepare for update
                        record_to_update = {
                            'id': existing_record_map[key],
                            'fields': session_fields
                        }
                        records_to_update.append(record_to_update)
                        processed_records.add(key)
                    else:
                        # New record, prepare for creation
                        records_to_create.append(session_fields)
                        processed_records.add(key)

            # Process sessions where the speaker is moderating
            moderating_sessions = fields.get('Moderating', [])
            if moderating_sessions:
                # Ensure moderating_sessions is a list
                if not isinstance(moderating_sessions, list):
                    moderating_sessions = [moderating_sessions]

                # Create a record for each moderating session
                for session_id in moderating_sessions:
                    session_fields = {
                        'Name': speaker_name,
                        'Speaker': [record_id],
                        'Session': [session_id],
                        'Role': 'Moderating',
                        'S Channel': s_channel
                    }

                    # Check if this record already exists
                    key = f"{record_id}_{session_id}_Moderating"
                    if key in existing_record_map:
                        # Record exists, prepare for update
                        record_to_update = {
                            'id': existing_record_map[key],
                            'fields': session_fields
                        }
                        records_to_update.append(record_to_update)
                        processed_records.add(key)
                    else:
                        # New record, prepare for creation
                        records_to_create.append(session_fields)
                        processed_records.add(key)

        log(f"Records to create: {len(records_to_create)}")
        log(f"Records to update: {len(records_to_update)}")

        # Create new records in batches
        if records_to_create:
            log("Creating new records in batches...")
            batch_size = 10
            created_count = 0

            for i in range(0, len(records_to_create), batch_size):
                batch = records_to_create[i:i+batch_size]
                dest_table.batch_create(batch)
                created_count += len(batch)
                log(f"Created batch {i//batch_size + 1}, total: {created_count}")
                time.sleep(0.5)

            log(f"Successfully created {created_count} new records")

        # Update existing records in batches
        if records_to_update:
            log("Updating existing records in batches...")
            batch_size = 10
            updated_count = 0

            for i in range(0, len(records_to_update), batch_size):
                batch = records_to_update[i:i+batch_size]
                dest_table.batch_update(batch)
                updated_count += len(batch)
                log(f"Updated batch {i//batch_size + 1}, total: {updated_count}")
                time.sleep(0.5)

            log(f"Successfully updated {updated_count} existing records")

        # Set output for GitHub Actions
        if os.environ.get("GITHUB_ACTIONS") == "true":
            with open(os.environ.get("GITHUB_OUTPUT", ""), "a") as f:
                f.write(f"last_sync_time={datetime.now().strftime('%Y-%m-%dT%H:%M:%S.000Z')}\n")

        log("Sync completed successfully")

    except Exception as e:
        log(f"ERROR: An error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    process_airtable_data()