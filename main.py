from datetime import datetime, date, time, timedelta
import os.path
import zoneinfo
from tzlocal import get_localzone_name
import sqlite3
import sys
from typing import Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class Event:
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime,):

        self.start_dt: datetime = start_dt
        self.end_dt: datetime = end_dt
        self.duration: float = (end_dt - start_dt).total_seconds()
        self.summary: str = summary
        self.valid_start_dt: datetime = start_dt
        self.valid_end_dt: datetime = end_dt


    def get_start_end_dt(self) -> Tuple[datetime, datetime]:
        return self.start_dt, self.end_dt

class FixedEvent(Event):
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime):

        super().__init__(summary, start_dt, end_dt)
        self.is_flexible: bool = False
        self.valid_start_dt: datetime = start_dt
        self.valid_end_dt: datetime = end_dt

    def __str__(self):
        return f"Fixed Event {self.summary} ({self.start_dt} to {self.end_dt})"

    def __repr__(self):
        return (f"FixedEvent(summary: {self.summary},\n"
                f"start_dt: {self.start_dt}\n"
                f"end_dt: {self.end_dt}\n"
                f"duration: {self.duration}")


class FlexibleEvent(Event):
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime,
                 valid_start_dt: datetime,
                 valid_end_dt: datetime):

        super().__init__(summary, start_dt, end_dt)
        self.is_flexible: bool = True
        self.valid_start_dt: datetime = valid_start_dt
        self.valid_end_dt: datetime = valid_end_dt

    def __str__(self):
        return f"Flexible Event {self.summary} ({self.start_dt} to {self.end_dt}) (Valid range: {self.valid_start_dt} to {self.valid_end_dt})"

    def __repr__(self):
        return (f"FlexibleEvent(summary: {self.summary},\n"
                f"start_dt: {self.start_dt}\n"
                f"end_dt: {self.end_dt}\n"
                f"duration: {self.duration}\n"
                f"valid_start_dt: {self.valid_start_dt}\n"
                f"valid_end_dt: {self.valid_end_dt})")

    def get_valid_range(self) -> Tuple[datetime, datetime]:
        return self.valid_start_dt, self.valid_end_dt


# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_system_tz() -> str:
    #Gets local timezone from system
    try:
        return get_localzone_name()
    except Exception as e:
        print(f"Error getting system timezone: {e}")
        sys.exit(1)

#Store local timezone in global var
TIMEZONE = get_system_tz()

def create_table()-> None:
    conn = sqlite3.connect(f"events.db")
    print("Opened database successfully")

    conn.execute('''
    CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    event_start_dt TEXT NOT NULL,
    event_end_dt TEXT NOT NULL,
    valid_start_dt TEXT,
    valid_end_dt TEXT,
    timezone TEXT NOT NULL
    )
    ''')

    conn.commit()
    conn.close()


def add_event_to_db(event: Event) -> None:
    conn = sqlite3.connect(f"events.db")
    cursor = conn.cursor()

    #Check if event already exists in the DB
    cursor.execute('''
        SELECT 1 FROM events
        WHERE summary = ? AND event_start_dt = ? AND event_end_dt = ?
        LIMIT 1
    ''', (event.summary, event.start_dt.isoformat(), event.end_dt.isoformat()))

    if cursor.fetchone():
        print(f"Event with name '{event.summary}' already exists in database")
        return

    cursor.execute('''
        INSERT INTO events (summary, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, timezone)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (event.summary,
          event.start_dt.isoformat(),
          event.end_dt.isoformat(),
          event.valid_start_dt.isoformat(),
          event.valid_end_dt.isoformat(),
          TIMEZONE))

    conn.commit()
    conn.close()

    print("Event added to database successfully")





def convert_str_to_time(time_str: str) -> time:
    #Converts string input in the format HH:MM into timezone.time object
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except ValueError as e:
        print(f"Invalid time format: {e}")
        sys.exit(1)

def convert_str_to_date(date_str: str) -> date:
    #Converts string input in the format dd-mm-YYYY to a datetime.date object
    try:
        return datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError as e:
        print(f"Invalid date format: {e}")
        sys.exit(1)


def authenticate():
    #Creates the json access and refresh tokens to authenticate user to the application
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh token: {e}")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def get_events_on_day(creds, date_str: str):
    #Returns a list of all events on a given day
    try:
        service = build("calendar", "v3", credentials=creds)

        #Convert string date input to the correct datetime format
        day = convert_str_to_date(date_str)
        start_datetime = datetime.combine(day, time.min).isoformat() + 'Z'
        end_datetime = datetime.combine(day, time.max).isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime,
            timeMax=end_datetime,
            singleEvents=True,
            orderBy='startTime'
        ).execute()


        events = events_result.get('items', [])

        return events

    except HttpError as error:
        print(f"An error occurred: {error}")
        quit()

def user_create_event(date_str: str, start_time_str: str, duration: int, is_flexible: bool, summary: str) -> Event:
    day = convert_str_to_date(date_str)
    start_time = convert_str_to_time(start_time_str)
    start_dt = datetime.combine(day, start_time, tzinfo=zoneinfo.ZoneInfo(TIMEZONE))
    end_dt = start_dt + timedelta(minutes=duration)
    event = None

    if not is_flexible:
        event = FixedEvent(summary, start_dt, end_dt)
    else:
        pass

    return event

def add_event_to_calendar(creds, event: Event)-> None:
    #Adds an event to the Google calendar

    #Convert date and time to the correct format for request body
    start_formatted = event.start_dt.isoformat()
    end_formatted = event.end_dt.isoformat()


    #Create request body
    event = {
        'summary': event.summary,
        'start': {
            'dateTime': start_formatted,
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_formatted,
            'timeZone': TIMEZONE,
        },
        'reminders': {
            'useDefault': True,
        }
    }

    #Send API call to insert event into the calendar
    try:
        service = build("calendar", "v3", credentials=creds)
        event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Event created: {event.get('htmlLink')}")

    except HttpError as error:
        print(f"An error occurred: {error}")
        sys.exit(1)

def print_events(events):
    #Prints list of events to the terminal (for debug purposes)
    if not events:
      print("No upcoming events found.")
      return

    for event in events:
      start = event["start"].get("dateTime", event["start"].get("date"))
      print(start, event["summary"])

def add_events_on_day_to_db(creds, date_str: str):
    #Adds existing events from the google calendar on a given day to the DB
    events = get_events_on_day(creds, date_str)
    for event in events:
        start_str = event["start"].get("dateTime", event["start"].get("date"))
        end_str = event["end"].get("dateTime", event["end"].get("date"))

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        add_event_to_db(FixedEvent(event["summary"], start_dt, end_dt))



def main():
    creds = authenticate()

    new_event = user_create_event("21-06-2025", "16:00", 30, False, "Test API")
    #print(new_event)
    add_event_to_calendar(creds, new_event)

    add_events_on_day_to_db(creds, "21-06-2025")


if __name__ == "__main__":
    main()


