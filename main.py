from datetime import datetime, date, time, timedelta
import os.path
import zoneinfo
from tzlocal import get_localzone_name
import sqlite3
import sys
from typing import Tuple
from abc import ABC

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

class Event(ABC):
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime,):

        self.start_dt: datetime = start_dt
        self.end_dt: datetime = end_dt
        self.is_flexible: bool = False
        self.duration: float = (end_dt - start_dt).total_seconds()
        self.summary: str = summary
        self.valid_start_dt: datetime = start_dt
        self.valid_end_dt: datetime = end_dt


    def get_start_end_dt(self) -> Tuple[datetime, datetime]:
        return self.start_dt, self.end_dt

    def add_to_calendar(self, creds) -> None:
        # Adds an event to the Google calendar

        # Convert date and time to the correct format for request body
        start_formatted = self.start_dt.isoformat()
        end_formatted = self.end_dt.isoformat()

        # Create request body
        event = {
            'summary': self.summary,
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
        # Send API call to insert event into the calendar
        try:
            service = build("calendar", "v3", credentials=creds)
            event = service.events().insert(calendarId='primary', body=event).execute()
            print(f"Event created: {event.get('htmlLink')}")

        except HttpError as error:
            print(f"An error occurred: {error}")
            sys.exit(1)

    def is_duplicate(self, db_name: str) -> bool:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Check if event already exists in the DB
        cursor.execute('''
                       SELECT 1
                       FROM events
                       WHERE summary = ?
                         AND event_start_dt = ?
                         AND event_end_dt = ?
                       LIMIT 1
                       ''', (self.summary, self.start_dt.isoformat(), self.end_dt.isoformat()))

        if cursor.fetchone():
            print(f"Event with name '{self.summary}' already exists in database")
            cursor.execute('''
            UPDATE events SET last_updated = ?
            WHERE summary = ?
                AND event_start_dt = ?
                AND event_end_dt = ?
            ''', (datetime.now().isoformat(), self.summary, self.start_dt.isoformat(), self.end_dt.isoformat()))
            conn.commit()
            conn.close()
            return True

        conn.commit()
        conn.close()

        return False

    def add_to_db(self, db_name: str) -> bool:
        if self.is_duplicate(db_name):
            return False

        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        cursor.execute('''
                       INSERT INTO events (summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt,
                                           valid_end_dt, timezone, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ''', (self.summary,
                             int(self.is_flexible),
                             self.start_dt.isoformat(),
                             self.end_dt.isoformat(),
                             self.valid_start_dt.isoformat(),
                             self.valid_end_dt.isoformat(),
                             TIMEZONE,
                             datetime.now().isoformat()))

        conn.commit()
        conn.close()

        print("Event added to database successfully")
        return True

    def submit_event(self, creds, db_name) -> None:
        valid = self.add_to_db(db_name)
        if valid:
            self.add_to_calendar(creds)
            print(f"Submitted event {self.summary}")


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


class EventBuilder(ABC):
    def __init__(self):
        pass

    @staticmethod
    def _generate_dts(date_str: str, start_time_str: str, end_time_str: str) -> Tuple[datetime, datetime]:
        day = convert_str_to_date(date_str)
        start_time = convert_str_to_time(start_time_str)
        end_time = convert_str_to_time(end_time_str)
        start_dt = datetime.combine(day, start_time, tzinfo=zoneinfo.ZoneInfo(TIMEZONE))
        end_dt = datetime.combine(day, end_time, tzinfo=zoneinfo.ZoneInfo(TIMEZONE))

        return start_dt, end_dt

class FixedEventBuilder(EventBuilder):
    def __init__(self):
        super().__init__()

    def create_fixed_event(self, date_str: str, start_time_str: str, end_time_str: str, summary: str) -> FixedEvent:
        start_dt, end_dt = self._generate_dts(date_str, start_time_str, end_time_str)
        return FixedEvent(summary, start_dt, end_dt)


class FlexibleEventBuilder(EventBuilder):
    def __init__(self):
        super().__init__()

    def create_flexible_event(self, date_str: str, valid_start_time_str: str, valid_end_time_str: str, duration: int, summary: str) -> FlexibleEvent:
        valid_start_dt, valid_end_dt = self._generate_dts(date_str, valid_start_time_str, valid_end_time_str)
        init_end_dt = valid_start_dt + timedelta(minutes=duration)

        return FlexibleEvent(summary, valid_start_dt, init_end_dt, valid_start_dt, valid_end_dt)



def get_system_tz() -> str:
    #Gets local timezone from system
    try:
        return get_localzone_name()
    except Exception as e:
        print(f"Error getting system timezone: {e}")
        sys.exit(1)

#Store local timezone in global var
TIMEZONE = get_system_tz()

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

def create_table()-> None:
    conn = sqlite3.connect(f"events.db")
    print("Opened database successfully")

    conn.execute('''
    CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    is_flexible INTEGER NOT NULL,
    event_start_dt TEXT NOT NULL,
    event_end_dt TEXT NOT NULL,
    valid_start_dt TEXT,
    valid_end_dt TEXT,
    timezone TEXT NOT NULL,
    last_updated TEXT NOT NULL
    )
    ''')

    conn.commit()
    conn.close()



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


def print_events(events):
    #Prints list of events to the terminal (for debug purposes)
    if not events:
      print("No upcoming events found.")
      return

    for event in events:
      start = event["start"].get("dateTime", event["start"].get("date"))
      print(start, event["summary"])

def add_events_on_day_to_db(creds, db_name: str, date_str: str):
    #Adds existing events from the Google calendar on a given day to the DB
    events = get_events_on_day(creds, date_str)
    for event in events:
        start_str = event["start"].get("dateTime", event["start"].get("date"))
        end_str = event["end"].get("dateTime", event["end"].get("date"))

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        FixedEvent(event["summary"], start_dt, end_dt).add_to_db(db_name)



def main():
    creds = authenticate()
    add_events_on_day_to_db(creds, "events.db", "27-06-2025")
    eb = FlexibleEventBuilder()
    new_event = eb.create_flexible_event("27-06-2025", "18:00", "23:00", 30, "Test API Flex")
    #print(new_event)
    new_event.submit_event(creds, db_name="events.db")




if __name__ == "__main__":
    main()
    #create_table()


