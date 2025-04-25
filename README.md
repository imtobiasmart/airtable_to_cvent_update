# Airtable to Cvent Event Sync

A Python application that synchronizes session data from Airtable to Cvent, automatically updating event sessions when records are modified.

## Overview

This application monitors an Airtable base for recently modified session records and updates corresponding sessions in Cvent. It's designed for event management where session information (speakers, moderators, titles, descriptions, etc.) needs to be kept in sync between your Airtable planning system and the Cvent event platform.

## Features

- Automatically syncs Airtable session data to Cvent
- Updates existing sessions with modified data
- Handles session details including:
  - Title and description
  - Start and end times
  - Locations
  - Speakers and moderators (with correct categorization)
  - Session types and tags
  - Custom fields
- Converts Markdown-formatted descriptions to HTML
- Intelligent sync that preserves existing data when not explicitly changed
- Status-based control over which records get synchronized

## Requirements

- Python 3.6+
- Cvent API access with client credentials
- Airtable account and API key

## Dependencies

- `requests` - HTTP client for API calls
- `pyairtable` - Airtable API client
- `pytz` - Timezone handling

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd airtable-cvent-sync
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Set up environment variables (see Configuration section)

## Configuration

Set the following environment variables:

### Cvent Configuration
- `CVENT_CLIENT_ID` - Your Cvent API client ID
- `CVENT_CLIENT_SECRET` - Your Cvent API client secret
- `CVENT_EVENT_ID` - The ID of your Cvent event

### Airtable Configuration
- `AIRTABLE_API_KEY` - Your Airtable API key
- `AIRTABLE_BASE_ID` - The ID of your Airtable base
- `AIRTABLE_TABLE_NAME` - Name of the sessions table
- `AIRTABLE_VIEW_ID` - ID of the view to query for session data

## Airtable Structure Requirements

Your Airtable base should have the following fields in the sessions table:

- `Cvent Session ID` - ID of the corresponding session in Cvent (required)
- `Session Title (<100 characters)` - Session title
- `S25 Start Date/Time` - Session start date/time in Pacific Time 
- `S25 End Date/Time` - Session end date/time in Pacific Time
- `Description (<2500 characters)` - Session description (supports Markdown formatting)
- `W Room Text` - Session location name (must match Cvent location names)
- `Speaker Code (from Speaker)` - List of speaker codes that match Cvent speaker codes
- `Moderator Code` - List of moderator codes that match Cvent speaker codes
- `W Channel Text` - Session stage/track
- `W Presentation Type Text` - Session type
- `Website Tags (SELECT 3 MAX)` - Session tags
- `Upload Status` - Status field to control sync behavior

## Usage

Run the script manually or set it up as a scheduled job:

```
python main.py
```

The script will:
1. Check for Airtable session records modified in the last hour
2. For each modified record with a Cvent Session ID and allowed upload status, update the Cvent session

## Upload Status Control

The script only syncs records with the following upload statuses:
- "Upload Complete"
- "Changed - Ready for Re-Upload"
- "Ready for Upload"

Records with other statuses will be skipped.

## Time Zone Handling

The script converts times from Pacific Time (America/Los_Angeles) in Airtable to UTC for Cvent. Ensure your Airtable times are properly formatted as "MM/DD/YYYY HH:MM AM/PM" in Pacific Time.

## Speaker and Moderator Handling

Speaker and moderator assignments are handled by:
1. Matching speaker/moderator codes between Airtable and Cvent
2. Assigning the appropriate speaker category in Cvent
3. Adding/removing speakers based on Airtable data
4. Updating speaker categories if they've changed

## Custom Fields

The script handles custom fields used in Cvent:
- "stage" - Session stage/track
- "type" - Session type
- "tags" - Session tags

## Markdown to HTML Conversion

The script converts Markdown formatting in descriptions to HTML:
- **bold** → \<strong\>bold\</strong\>
- _italic_ → \<i\>italic\</i\>
- **_bold italic_** → \<strong\>\<i\>bold italic\</i\>\</strong\>
- [link text](url) → \<a href="url"\>link text\</a\>

## Error Handling

The script provides error messages when:
- API requests fail
- Speakers can't be assigned
- Fields can't be updated

## Logging

The script logs information about its operations to the standard output.
