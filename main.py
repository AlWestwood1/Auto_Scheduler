from datetime import datetime, date, time, timedelta
import os.path
import zoneinfo
from tzlocal import get_localzone_name
import sqlite3
import sys
from typing import Tuple, List
from abc import ABC
import copy
from enum import Enum

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

class EventType(Enum):
    FIXED = 0
    FLEXIBLE = 1
    ALL = 2

class OrderBy(Enum):
    START = "valid_start_dt, valid_end_dt"
    END = "valid_end_dt, valid_start_dt"

class Event(ABC):
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime,
                 google_id: str = None):

        self.start_dt: datetime = start_dt
        self.end_dt: datetime = end_dt
        self.is_flexible: bool = False
        self.duration: float = (end_dt - start_dt).total_seconds() / 60
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
        start_dt = datetime.combine(day, start_time, tzinfo=zoneinfo.ZoneInfo(Timezone().timezone))
        end_dt = datetime.combine(day, end_time, tzinfo=zoneinfo.ZoneInfo(Timezone().timezone))

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

        conn = sqlite3.connect('events.db')
        cursor = conn.cursor()
        # TODO: work out way of finding the best start/end times in the case of there being multiple events to minimise clashes (e.g. put event where there is just 1 clash rather than 2)
        # Fetch list of all events in the valid window in chronological order
        cursor.execute('''
                       SELECT summary, event_start_dt, event_end_dt
                       FROM events
                       WHERE (event_start_dt BETWEEN ? AND ?)
                          OR (? BETWEEN event_start_dt AND event_end_dt)
                          OR (? BETWEEN event_start_dt AND event_end_dt)
                       ORDER BY event_start_dt''',
                       (valid_start_dt.isoformat(), valid_end_dt.isoformat(), valid_start_dt.isoformat(),
                        valid_end_dt.isoformat()))

        events = []
        for event in cursor.fetchall():
            events.append(FixedEvent(event[0], datetime.fromisoformat(event[1]), datetime.fromisoformat(event[2])))

        conn.close()

        slot_finder = FlexSlotFinder(valid_start_dt, valid_end_dt, duration)
        start_dt, end_dt = slot_finder.find_valid_slot(events)

        if not slot_finder.no_clashes:
            print("No valid time slot can be found for this event.")
            sys.exit(1)

        #Create FlexibleEvent from args (event will start at valid_start_dt and last duration minutes)
        return FlexibleEvent(summary, start_dt, end_dt, valid_start_dt, valid_end_dt)


class FlexSlotFinder:
    def __init__(self, valid_start_dt: datetime, valid_end_dt: datetime, duration: int):
        self.valid_start_dt = valid_start_dt
        self.valid_end_dt = valid_end_dt
        self.duration = duration
        self.no_clashes = False
        self.start_dt = None
        self.end_dt = None

    def find_valid_slot(self, events: List[FixedEvent]) -> Tuple[datetime, datetime]:

        # Iterate through events
        # If the interval between the end time of one event and the start of the next is larger than the duration, put the start/end times in this space
        for i in range(0, len(events) + 1):
            prev_event_end = self.valid_start_dt if i == 0 else events[i - 1].end_dt
            next_event_start = self.valid_end_dt if i == len(events) else events[i].start_dt
            candidate_start_dt = prev_event_end
            candidate_end_dt = prev_event_end + timedelta(minutes=self.duration)
            if candidate_end_dt <= next_event_start and candidate_end_dt <= self.valid_end_dt:
                self.no_clashes = True
                self.start_dt = candidate_start_dt
                self.end_dt = candidate_end_dt

                return self.start_dt, self.end_dt

        return self.valid_start_dt, self.valid_start_dt + timedelta(minutes=self.duration)


class Timezone(metaclass=Singleton):
    def __init__(self):
        self.timezone = self.local_tz()

    @staticmethod
    def local_tz() -> str:
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


class Database(metaclass=Singleton):
    #TODO: Delete event

    def __init__(self) -> None:
        self.db_name = "events.db"
        self.__create_table()

    def __create_table(self) -> None:
        """
        Creates empty SQLite table for events to be stored in
        :return: none
        """

        # Create new database called 'events.db' and connect
        conn = sqlite3.connect(self.db_name)
        print("Opened database successfully")

        # Create a new table called events, containing columns required for events to be stored
        conn.execute('''
                     CREATE TABLE IF NOT EXISTS events
                     (
                         id             INTEGER PRIMARY KEY AUTOINCREMENT,
                         summary        TEXT     NOT NULL,
                         is_flexible    INTEGER  NOT NULL,
                         event_start_dt TEXT     NOT NULL,
                         event_end_dt   TEXT     NOT NULL,
                         duration       INTEGER  NOT NULL,
                         valid_start_dt TEXT,
                         valid_end_dt   TEXT,
                         timezone       TEXT     NOT NULL,
                         google_id      TEXT,
                         last_updated   DATETIME NOT NULL
                     )
                     ''')

        # Close connection
        conn.commit()
        conn.close()


    def __update_timestamp(self, event: Event) -> None:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
                       UPDATE events
                       SET last_updated = ?
                       WHERE summary = ?
                         AND event_start_dt = ?
                         AND event_end_dt = ?
                       ''', (datetime.now().isoformat(), event.summary, event.start_dt.isoformat(),
                             event.end_dt.isoformat()))
        conn.commit()
        conn.close()

    def exists(self, event: Event) -> bool:
        """
        Checks whether an event already exists in the database
        :param event: Event to check duplicates for
        :return: True if event already exists, False otherwise
        """

        #Connect to db
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Check if event with same name, start time and end time exists in the DB
        cursor.execute('''
                       SELECT 1
                       FROM events
                       WHERE summary = ?
                         AND event_start_dt = ?
                         AND event_end_dt = ?
                       LIMIT 1
                       ''', (event.summary, event.start_dt.isoformat(), event.end_dt.isoformat()))

        #If it exists, update the 'last modified' column of the entry in the DB and close connection (return True)
        if cursor.fetchone():
            conn.close()
            print(f"Event with name '{event.summary}' already exists in database")
            self.__update_timestamp(event)
            return True

        #If it doesn't exist, close connection and return False
        conn.close()
        return False

    def add_event(self, event: Event) -> int:
        """
        Adds an event to the database
        :param event: Event to add to db
        :return: New eventID if successful, -1 otherwise
        """

        # If the event is a duplicate, return False
        if self.exists(event):
            return -1

        # Connect to the DB
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Add a new row with event params into the DB
        cursor.execute('''
                       INSERT INTO events (summary, is_flexible, event_start_dt, event_end_dt, duration, valid_start_dt,
                                           valid_end_dt, timezone, google_id, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       RETURNING id
                       ''', (event.summary,
                             int(event.is_flexible),
                             event.start_dt.isoformat(),
                             event.end_dt.isoformat(),
                             event.duration,
                             event.valid_start_dt.isoformat(),
                             event.valid_end_dt.isoformat(),
                             Timezone().timezone,
                             event.google_id,
                             datetime.now().isoformat()))

        new_id = cursor.fetchone()[0]
        # Close connection to DB
        conn.commit()
        conn.close()

        # Print success message and return True
        print("Event added to database successfully")
        return new_id

    def get_events(self, from_dt: datetime, to_dt: datetime, event_type: EventType = EventType.ALL, order_by: OrderBy = OrderBy.START) -> List[Event]:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        if event_type == EventType.ALL:
            cursor.execute(f"""
                           SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                           FROM events
                           WHERE (event_start_dt BETWEEN ? AND ?)
                           ORDER BY {order_by.value}""",
                           (from_dt.isoformat(), to_dt.isoformat(), event_type.value))

        else:
            cursor.execute(f"""
                           SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                           FROM events
                           WHERE (event_start_dt BETWEEN ? AND ?)
                             AND (is_flexible = ?)
                           ORDER BY {order_by.value}""",
                           (from_dt.isoformat(), to_dt.isoformat(), event_type.value))

        events = []
        for event in cursor.fetchall():
            if event[1] == 0:
                events.append(FixedEvent(event[0], datetime.fromisoformat(event[2]), datetime.fromisoformat(event[3]), event[6]))
            else:
                events.append(
                    FlexibleEvent(event[0], datetime.fromisoformat(event[2]), datetime.fromisoformat(event[3]),
                                  datetime.fromisoformat(event[4]), datetime.fromisoformat(event[5]), event[6]))

        conn.close()
        return events

    def update_event(self, event: Event):
        #TODO add error handling for events that don't exist
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute('''
                       UPDATE events
                       SET summary = ?,
                           event_start_dt = ?,
                           event_end_dt   = ?,
                           duration = ?,
                           valid_start_dt = ?,
                           valid_end_dt = ?,
                           timezone = ?,
                           last_updated = ?
                       WHERE google_id = ?
       ''', (event.summary,
                        event.start_dt.isoformat(),
                        event.end_dt.isoformat(),
                        event.duration,
                         event.valid_start_dt.isoformat(),
                         event.valid_end_dt.isoformat(),
                         Timezone().timezone,
                        datetime.now().isoformat(),
                        event.google_id),)
        conn.commit()
        conn.close()


    def update_google_id(self, db_id: int, google_id: str) -> None:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute('''
                       UPDATE events
                       SET google_id = ?
                       WHERE id = ?
                       ''', (google_id, db_id))

        conn.commit()
        conn.close()

class GoogleCalendar(metaclass=Singleton):
    def __init__(self):
        self.creds = self.__authenticate()
        self.calendar_id = "primary"

    @staticmethod
    def __authenticate():
        # Creates the json access and refresh tokens to authenticate user to the application
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

    def add_event(self, event: Event) -> str:
        """
        Adds an event to the Google calendar
        :param event: event to add to calendar
        :return: None
        """

        # Convert date and time to the correct format for request body
        start_formatted = event.start_dt.isoformat()
        end_formatted = event.end_dt.isoformat()

        # Create request body
        event_json = {
            'summary': event.summary,
            'start': {
                'dateTime': start_formatted,
                'timeZone': Timezone().timezone,
            },
            'end': {
                'dateTime': end_formatted,
                'timeZone': Timezone().timezone,
            },
            'reminders': {
                'useDefault': True,
            }
        }
        # Send API call to insert event into the calendar
        try:
            service = build("calendar", "v3", credentials=self.creds)
            response = service.events().insert(calendarId=self.calendar_id, body=event_json).execute()
            print(f"Event created: {response.get('htmlLink')}")

            return response.get('id')

        except HttpError as error:
            print(f"An error occurred: {error}")
            sys.exit(1)

    def get_events(self, start_dt: datetime, end_dt: datetime) -> List[Event]:
        """
        Returns a list of all events on a given day
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: List of all events on the requested day
        """
        start_formatted = start_dt.isoformat() + 'Z'
        end_formatted = end_dt.isoformat() + 'Z'

        try:
            service = build("calendar", "v3", credentials=self.creds)

            # Send request to API to return list of events on chosen day
            events_result = service.events().list(
                calendarId=GoogleCalendar().calendar_id,
                timeMin=start_formatted,
                timeMax=end_formatted,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            # Generate list from JSON return body
            events_json = events_result.get('items', [])
            events_list = []
            for event in events_json:
                summary = event['summary']
                start_str = event["start"].get("dateTime", event["start"].get("date"))
                end_str = event["end"].get("dateTime", event["end"].get("date"))
                event_id = event["id"]

                events_list.append(FixedEvent(summary, datetime.fromisoformat(start_str), datetime.fromisoformat(end_str), event_id))

            return events_list

        except HttpError as error:
            print(f"An HTTP error occurred: {error}")
            print(error.content)
            sys.exit(1)


    def update_event(self, event: Event):
        service = build("calendar", "v3", credentials=self.creds)

        service.events().patch(
            calendarId=self.calendar_id,
            eventId=event.google_id,
            body={
                "summary": event.summary,
                "start": {
                    "dateTime": event.start_dt.isoformat(),
                    "timeZone": Timezone().timezone,
                },
                "end": {
                    "dateTime": event.end_dt.isoformat(),
                    "timeZone": Timezone().timezone,
                }
            }
        ).execute()
        print(f"Event {event.summary} updated")

class EventManager:
    def __init__(self):
        pass

    @staticmethod
    def sync_gc_to_db(start_dt: datetime, end_dt: datetime) -> None:
        """
        Adds existing events from the Google calendar on a given day to the DB
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: None
        """
        # Get list of all events on day from Google calendar
        events = GoogleCalendar().get_events(start_dt, end_dt)

        for event in events:
            Database().add_event(event)

    @staticmethod
    def submit_event(event) -> None:
        """
        Adds an event to the database and google calendar
        :param event: Event to add to calendar and db
        :return: None
        """
        #Add event to database, return whether it was added successfully
        db_id = Database().add_event(event)

        #If event was added to the DB successfully, add to the Google Calendar
        if db_id != -1:
            google_id = GoogleCalendar().add_event(event)
            Database().update_google_id(db_id, google_id)
            print(f"Submitted event {event.summary}")


class DateTimeConverter:

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def convert_str_to_dt(date_str: str) -> datetime:
        try:
            return datetime.strptime(date_str, "%d-%m-%Y")
        except ValueError as e:
            print(f"Invalid date format: {e}")
            sys.exit(1)

    @staticmethod
    def get_cur_midnight(dt: datetime) -> datetime:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def get_next_midnight(dt: datetime) -> datetime:
        dt_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt_midnight + timedelta(days=1)

class FlexEventOptimiser:

    @staticmethod
    def move_events(flex_events, fixed_events):
        invalid_events = []
        valid_events = []

        for event in flex_events:
            slot_finder = FlexSlotFinder(event.valid_start_dt, event.valid_end_dt, event.duration)
            new_start_dt, new_end_dt = slot_finder.find_valid_slot(fixed_events)
            updated_event = FlexibleEvent(event.summary, new_start_dt, new_end_dt, event.valid_start_dt,
                                          event.valid_end_dt, event.google_id)
            if slot_finder.no_clashes:
                valid_events.append(updated_event)
                fixed_events.append(FixedEvent(updated_event.summary, updated_event.start_dt, updated_event.end_dt))
                fixed_events.sort(key=lambda x: x.start_dt)
            else:
                invalid_events.append(updated_event)

        return valid_events, invalid_events

    @staticmethod
    def update_moved_events(events):

        for event in events:
            Database().update_event(event)
            GoogleCalendar().update_event(event)


    def optimise_flex_events(self, dt: datetime) -> None:
        cur_midnight = DateTimeConverter().get_cur_midnight(dt)
        next_midnight = DateTimeConverter().get_next_midnight(dt)

        fixed_events_st = Database().get_events(cur_midnight, next_midnight, EventType.FIXED)
        fixed_events_et = copy.deepcopy(fixed_events_st)

        flex_events_st = Database().get_events(cur_midnight, next_midnight, EventType.FLEXIBLE, OrderBy.START)
        flex_events_et = Database().get_events(cur_midnight, next_midnight, EventType.FLEXIBLE, OrderBy.END)

        valid_events_st, invalid_events_st = self.move_events(flex_events_st, fixed_events_st)
        valid_events_et, invalid_events_et = self.move_events(flex_events_et, fixed_events_et)

        if len(valid_events_st) > len(valid_events_et):
            if len(invalid_events_st) > 0:
                print(f"Invalid events found: {invalid_events_st}")

            self.update_moved_events(valid_events_st)
        else:
            if len(invalid_events_st) > 0:
                print(f"Invalid events found: {invalid_events_et}")
            self.update_moved_events(valid_events_et)


def print_events(events):
    #Prints list of events to the terminal (for debug purposes)
    if not events:
      print("No upcoming events found.")
      return

    for event in events:
      start = event["start"].get("dateTime", event["start"].get("date"))
      print(start, event["summary"])



def main():
    dtc = DateTimeConverter()
    dt = dtc.convert_str_to_dt("05-08-2025")
    start_dt = dtc.get_cur_midnight(dt)
    end_dt = dtc.get_next_midnight(dt)


    em = EventManager()
    em.sync_gc_to_db(start_dt, end_dt)
    """
    eb = FlexibleEventBuilder()
    new_event = eb.create_flexible_event("05-08-2025",
                                         "19:00",
                                         "21:00",
                                         30,
                                         "Test Flexible event 4")
    #print(new_event)
    new_event.submit_event(creds, db_name="events.db")
    """
    FlexEventOptimiser().optimise_flex_events(dt)



if __name__ == "__main__":
    main()
    #create_table()


