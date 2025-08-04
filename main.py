from datetime import datetime, date, time, timedelta
import os.path
import zoneinfo
from tzlocal import get_localzone_name
import sqlite3
import sys
from typing import Tuple, List
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
                 end_dt: datetime,
                 google_id: str = None):

        self.start_dt: datetime = start_dt
        self.end_dt: datetime = end_dt
        self.is_flexible: bool = False
        self.duration: float = (end_dt - start_dt).total_seconds()
        self.summary: str = summary
        self.valid_start_dt: datetime = start_dt
        self.valid_end_dt: datetime = end_dt
        self.google_id: str = google_id


    def get_start_end_dt(self) -> Tuple[datetime, datetime]:
        """
        Returns start_dt and end_dt
        :return: start_dt, end_dt
        """
        return self.start_dt, self.end_dt

    def add_to_calendar(self, creds) -> None:
        """
        Adds an event to the Google calendar
        :param creds: Google API credentials
        :return: None
        """

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
            self.google_id = event.get('id')

        except HttpError as error:
            print(f"An error occurred: {error}")
            sys.exit(1)

    def is_duplicate(self, db_name: str) -> bool:
        """
        Checks whether an event already exists in the database
        :param db_name: database file name
        :return: True if event already exists, False otherwise
        """

        #Connect to db
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Check if event with same name, start time and end time exists in the DB
        cursor.execute('''
                       SELECT 1
                       FROM events
                       WHERE summary = ?
                         AND event_start_dt = ?
                         AND event_end_dt = ?
                       LIMIT 1
                       ''', (self.summary, self.start_dt.isoformat(), self.end_dt.isoformat()))

        #If it exists, update the 'last modified' column of the entry in the DB and close connection (return True)
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

        #If it doesn't exist, close connection and return False

        conn.commit()
        conn.close()

        return False

    def add_to_db(self, db_name: str) -> int:
        """
        Adds an event to the database
        :param db_name: database file name
        :return: True if added to the database successfully, False otherwise
        """

        #If the event is a duplicate, return False
        if self.is_duplicate(db_name):
            return -1

        #Connect to the DB
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        #Add a new row with event params into the DB
        cursor.execute('''
                       INSERT INTO events (summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt,
                                           valid_end_dt, timezone, google_id, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       RETURNING id
                       ''', (self.summary,
                             int(self.is_flexible),
                             self.start_dt.isoformat(),
                             self.end_dt.isoformat(),
                             self.valid_start_dt.isoformat(),
                             self.valid_end_dt.isoformat(),
                             TIMEZONE,
                             self.google_id,
                             datetime.now().isoformat()))

        new_id = cursor.fetchone()[0]
        #Close connection to DB
        conn.commit()
        conn.close()

        #Print success message and return True
        print("Event added to database successfully")
        return new_id

    def submit_event(self, creds, db_name) -> None:
        """
        Adds an event to the database and google calendar
        :param creds: Google API credentials
        :param db_name: database file name
        :return: None
        """
        #Add event to database, return whether it was added successfully
        db_id = self.add_to_db(db_name)

        #If event was added to the DB successfully, add to the Google Calendar
        if db_id != -1:
            self.add_to_calendar(creds)

            conn = sqlite3.connect(db_name)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE events
                SET google_id = ?
                WHERE id = ?
                ''', (self.google_id, db_id))

            conn.commit()
            conn.close()

            print(f"Submitted event {self.summary}")


class FixedEvent(Event):
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime,
                 google_id: str = None):

        super().__init__(summary, start_dt, end_dt, google_id)
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
                 valid_end_dt: datetime,
                 google_id: str = None):

        super().__init__(summary, start_dt, end_dt, google_id)
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
        """
        Gets valid start and end datetimes for the flexible event
        (this is NOT the event start and end times, but the range in which the flexible event can be created in)
        :return: valid start and end datetimes for the flexible event
        """
        return self.valid_start_dt, self.valid_end_dt


class EventBuilder(ABC):
    def __init__(self):
        pass

    @staticmethod
    def _generate_dts(date_str: str, start_time_str: str, end_time_str: str) -> Tuple[datetime, datetime]:
        """
        Creates start and end datetimes from the string dates and times provided by the user input
        :param date_str: String representation of the event date
        :param start_time_str: String representation of the start time
        :param end_time_str: String representation of the end time
        :return: Datetime representation of the start and end datetimes
        """
        day = convert_str_to_date(date_str)
        start_time = convert_str_to_time(start_time_str)
        end_time = convert_str_to_time(end_time_str)
        start_dt = datetime.combine(day, start_time, tzinfo=zoneinfo.ZoneInfo(TIMEZONE))
        end_dt = datetime.combine(day, end_time, tzinfo=zoneinfo.ZoneInfo(TIMEZONE))

        return start_dt, end_dt

class FixedEventBuilder(EventBuilder):
    def __init__(self):
        super().__init__()

    @staticmethod
    def check_fixed_clashes(db_name: str, start_dt: datetime, end_dt: datetime):
        # Connect to database
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT summary, event_start_dt, event_end_dt
                       FROM events
                       WHERE (is_flexible = 0)
                          AND(event_start_dt BETWEEN ? AND ?)
                          OR (? BETWEEN event_start_dt AND event_end_dt)
                          OR (? BETWEEN event_start_dt AND event_end_dt)
                       ORDER BY event_start_dt''',
                       (start_dt.isoformat(), end_dt.isoformat(), start_dt.isoformat(), end_dt.isoformat()))

        events = cursor.fetchall()
        conn.close()

        return events


    def create_fixed_event(self, date_str: str, start_time_str: str, end_time_str: str, summary: str) -> FixedEvent:
        """
        Creates a fixed event from the input parameters
        :param date_str: String representation of the event date
        :param start_time_str: String representation of the start time
        :param end_time_str: String representation of the end time
        :param summary: Event summary
        :return: FixedEvent object containing event information provided in input args
        """

        #Generate datetime representation of start and end dates
        start_dt, end_dt = self._generate_dts(date_str, start_time_str, end_time_str)

        clashes = self.check_fixed_clashes('events.db', start_dt, end_dt)
        if len(clashes) > 0:
            print(f"This event would clash with the following fixed events:")
            for clash in clashes:
                print(f"\t{clash[0]}")
            valid = False
            while not valid:
                cont = input("Do you want to continue? [y/N] ")
                if cont.lower() == 'n':
                    sys.exit(0)
                elif cont.lower() != 'y':
                    print('Invalid input - please try again')
                else:
                    valid = True


        #Create and return FixedEvent
        return FixedEvent(summary, start_dt, end_dt)


class FlexibleEventBuilder(EventBuilder):
    def __init__(self):
        super().__init__()
        self.can_create = False
        self.start_dt = None
        self.end_dt = None


    def find_start_end_times(self, db_name: str, valid_start_dt: datetime, valid_end_dt: datetime, duration: int) -> None:
        """
        Finds the earliest valid start and end times (i.e. without any clashes) for the event.
        :param db_name: Name of the database
        :param valid_start_dt: earliest valid start time for event
        :param valid_end_dt: latest valid end time for event
        :param duration: duration of event
        :return: None
        """
        #Connect to database
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        #TODO: work out way of finding the best start/end times in the case of there being multiple events to minimise clashes (e.g. put event where there is just 1 clash rather than 2)
        #Fetch list of all events in the valid window in chronological order
        cursor.execute('''
                       SELECT event_start_dt, event_end_dt
                       FROM events
                       WHERE (event_start_dt BETWEEN ? AND ?)
                          OR (? BETWEEN event_start_dt AND event_end_dt)
                           OR (? BETWEEN event_start_dt AND event_end_dt)
                       ORDER BY event_start_dt''', (valid_start_dt.isoformat(), valid_end_dt.isoformat(), valid_start_dt.isoformat(), valid_end_dt.isoformat()))

        events = cursor.fetchall()
        conn.close()

        #Iterate through events
        #If the interval between the end time of one event and the start of the next is larger than the duration, put the start/end times in this space
        for i in range(0, len(events)+1):
            prev_event_end = valid_start_dt if i == 0 else datetime.fromisoformat(events[i - 1][1])
            next_event_start = valid_end_dt if i == len(events) else datetime.fromisoformat(events[i][0])
            candidate_start_dt = prev_event_end
            candidate_end_dt = prev_event_end + timedelta(minutes=duration)
            if candidate_end_dt <= next_event_start and candidate_end_dt <= valid_end_dt:
                self.can_create = True
                self.start_dt = candidate_start_dt
                self.end_dt = candidate_end_dt


    def create_flexible_event(self, date_str: str, valid_start_time_str: str, valid_end_time_str: str, duration: int, summary: str) -> FlexibleEvent:
        """
        Creates a flexible event from the input parameters
        :param date_str: String representation of the event date
        :param valid_start_time_str: String representation of the start of the valid time range
        :param valid_end_time_str: String representation of the end of the valid time range
        :param duration: Duration of the flexible event
        :param summary: Event summary
        :return: FlexibleEvent object containing event information provided in input args
        """

        #Generate valid timerange datetimes from the valid start and end dates/times
        valid_start_dt, valid_end_dt = self._generate_dts(date_str, valid_start_time_str, valid_end_time_str)
        #Initalise the event end datetime as the valid start datetime + duration
        self.find_start_end_times("events.db", valid_start_dt, valid_end_dt, duration)

        if not self.can_create:
            print("No valid time slot can be found for this event.")
            sys.exit(1)

        #Create FlexibleEvent from args (event will start at valid_start_dt and last duration minutes)
        return FlexibleEvent(summary, self.start_dt, self.end_dt, valid_start_dt, valid_end_dt)



def get_system_tz() -> str:
    """
    Gets the system timezone
    :return: System timezone
    """

    #Get local timezone from system
    try:
        return get_localzone_name()
    except Exception as e:
        print(f"Error getting system timezone: {e}")
        sys.exit(1)

#Store local timezone in global var
TIMEZONE = get_system_tz()

def convert_str_to_time(time_str: str) -> time:
    """
    Converts string input in the format HH:MM into timezone.time object
    :param time_str: String representation of the time
    :return: time object representation of the time
    """
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except ValueError as e:
        print(f"Invalid time format: {e}")
        sys.exit(1)

def convert_str_to_date(date_str: str) -> date:
    """
    Converts string input in the format dd-mm-YYYY to a datetime.date object
    :param date_str: string representation of the date (in dd-mm-YYYY format)
    :return: date object representation of the date
    """
    try:
        return datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError as e:
        print(f"Invalid date format: {e}")
        sys.exit(1)

def create_table()-> None:
    """
    Creates empty SQLite table for events to be stored in
    :return: none
    """

    #Create new database called 'events.db' and connect
    conn = sqlite3.connect(f"events.db")
    print("Opened database successfully")

    #Create a new table called events, containing columns required for events to be stored
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
    google_id TEXT,
    last_updated DATETIME NOT NULL
    )
    ''')

    #Close connection
    conn.commit()
    conn.close()

def get_cur_midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def get_next_midnight(dt: datetime) -> datetime:
    dt_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt_midnight + timedelta(days=1)

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


def optimise_flex_events(db_name: str, dt: datetime) -> None:
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    cur_midnight = get_cur_midnight(dt)
    next_midnight = get_next_midnight(dt)


    cursor.execute('''
        SELECT google_id, event_start_dt, event_end_dt FROM events
        WHERE (event_start_dt BETWEEN ? AND ?)
            AND (is_flexible = 1)
        ORDER BY event_start_dt''',
        (cur_midnight.isoformat(), next_midnight.isoformat()))

    events = cursor.fetchall()
    print(events)
    conn.close()

def get_events_on_day(creds, date_str: str):
    """
    Returns a list of all events on a given day
    :param creds: Google API credentials
    :param date_str: String representation of the event date
    :return: List of all events on the requested day
    """
    try:
        service = build("calendar", "v3", credentials=creds)

        #Convert string date input to the correct datetime format
        day = convert_str_to_date(date_str)
        start_datetime = datetime.combine(day, time.min).isoformat() + 'Z'
        end_datetime = datetime.combine(day, time.max).isoformat() + 'Z'

        #Send request to API to return list of events on chosen day
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime,
            timeMax=end_datetime,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        #Generate list from JSON return body
        events = events_result.get('items', [])

        return events

    except HttpError as error:
        print(f"An HTTP error occurred: {error}")
        sys.exit(1)


"""
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
"""

def print_events(events):
    #Prints list of events to the terminal (for debug purposes)
    if not events:
      print("No upcoming events found.")
      return

    for event in events:
      start = event["start"].get("dateTime", event["start"].get("date"))
      print(start, event["summary"])

def add_events_on_day_to_db(creds, db_name: str, date_str: str):
    """
    Adds existing events from the Google calendar on a given day to the DB
    :param creds: Google API credentials
    :param db_name: Database file name
    :param date_str: String representation of the event date
    :return: None
    """
    #Get list of all events on day from Google calendar
    events = get_events_on_day(creds, date_str)


    for event in events:
        #Convert start and end dates into datetime objects
        start_str = event["start"].get("dateTime", event["start"].get("date"))
        end_str = event["end"].get("dateTime", event["end"].get("date"))
        event_id = event["id"]

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        #Create a FixedEvent object for each event and add it to the database
        FixedEvent(event["summary"], start_dt, end_dt, event_id).add_to_db(db_name)



def main():
    creds = authenticate()
    add_events_on_day_to_db(creds, "events.db", "04-08-2025")
    eb = FlexibleEventBuilder()
    new_event = eb.create_flexible_event("04-08-2025",
                                         "15:00",
                                         "19:00",
                                         30,
                                         "Test Flexible event")
    #print(new_event)
    new_event.submit_event(creds, db_name="events.db")

    optimise_flex_events('events.db', datetime(2025, 8, 4))



if __name__ == "__main__":
    main()
    #create_table()


