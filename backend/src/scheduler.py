from datetime import datetime, date, time, timedelta
import os.path
import zoneinfo
from tzlocal import get_localzone_name
import sqlite3
import sys
from typing import Tuple, List
from abc import ABC
from enum import Enum
import pulp

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar"]
WORKING_DIR = os.path.dirname(__file__)


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

    @classmethod
    def clear_instances(cls):
        cls._instances = {}


class EventType(Enum):
    """
    Enum class that defines the possible types of events
    """
    FIXED = 0
    FLEXIBLE = 1
    ALL = 2

class EventStatus(Enum):
    """
    Enum class that defines the possible statuses of events when updating the DB with latest info from the GC
    """
    UNCHANGED = 0
    NEW = 1
    MODIFIED = 2


class OrderBy(Enum):
    """
    Enum class that defines the two ways of ordering events when fetching from DB
    """
    START = "valid_start_dt, valid_end_dt"
    END = "valid_end_dt, valid_start_dt"


class Event(ABC):
    """
    Class that holds information about a calendar event
    """
    def __init__(self, summary: str,
                 start_dt: datetime,
                 end_dt: datetime,
                 google_id: str = None):
        self.start_dt: datetime = start_dt
        self.end_dt: datetime = end_dt
        self.is_flexible: bool = False
        self.summary: str = summary
        self.valid_start_dt: datetime = start_dt
        self.valid_end_dt: datetime = end_dt
        self.google_id: str = google_id

    @property
    def duration(self) -> int:
        return int((self.end_dt - self.start_dt).total_seconds() // 60)

    def to_json(self) -> dict:
        return {
            "summary": self.summary,
            "date": self.start_dt.date().isoformat(),
            "start_time": self.start_dt.time().isoformat(timespec='minutes'),
            "end_time": self.end_dt.time().isoformat(timespec='minutes'),
            "earliest_start": self.valid_start_dt.time().isoformat(timespec='minutes'),
            "latest_end": self.valid_end_dt.time().isoformat(timespec='minutes'),
            "duration_minutes": self.duration,
            "is_flexible": self.is_flexible,
            "google_id": self.google_id
        }

    def get_start_end_dt(self) -> Tuple[datetime, datetime]:
        """
        Returns start_dt and end_dt
        :return: start_dt, end_dt
        """
        return self.start_dt, self.end_dt


class FixedEvent(Event):
    """
    Fixed events can only exist at a fixed time, and will not be rearranged if a conflicting event is added
    E.g. a fixed event at 6-7pm will also have a valid window of 6-7pm. The event cannot be moved from this time
    """
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
    """
    Flexible events have a valid 'window' of time that the event can be moved within. If a conflicting event is added
    within the current event window, it can be moved anywhere within the valid event window to remove the conflict
    E.g. An event with a duration of 30 mins and a valid window of 6-7pm can exist at any time between 6-7pm but will
         always be 30 mins long
    """
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
    """
    Builder class for events
    """

    @staticmethod
    def _generate_dts(date_str: str, start_time_str: str, end_time_str: str) -> Tuple[datetime, datetime]:
        """
        Creates start and end datetimes from the string dates and times provided by the user input
        :param date_str: String representation of the event date
        :param start_time_str: String representation of the start time
        :param end_time_str: String representation of the end time
        :return: Datetime representation of the start and end datetimes
        """

        dtc = DateTimeConverter()
        day = dtc.convert_str_to_date(date_str)
        start_time = dtc.convert_str_to_time(start_time_str)
        end_time = dtc.convert_str_to_time(end_time_str)
        start_dt = datetime.combine(day, start_time, tzinfo=zoneinfo.ZoneInfo(Timezone().timezone))
        end_dt = datetime.combine(day, end_time, tzinfo=zoneinfo.ZoneInfo(Timezone().timezone))

        if end_dt <= start_dt:
            raise ValueError("Start time must be before end time")

        return start_dt, end_dt


class FixedEventBuilder(EventBuilder):
    """
    Builder class for fixed events
    """
    @staticmethod
    def create_fixed_event(start_time_str: str, end_time_str: str, summary: str) -> FixedEvent:
        """
        Creates a fixed event from the input parameters
        :param date_str: String representation of the event date
        :param start_time_str: String representation of the start time
        :param end_time_str: String representation of the end time
        :param summary: Event summary
        :return: FixedEvent object containing event information provided in input args
        """
        if not summary or summary == '':
            raise ValueError("Summary cannot be empty")

        #Generate datetime representation of start and end dates
        try:
            start_dt = datetime.fromisoformat(start_time_str)
            end_dt = datetime.fromisoformat(end_time_str)
            #start_dt, end_dt = self._generate_dts(date_str, start_time_str, end_time_str)
        except ValueError as e:
            print(e)
            sys.exit(1)

        """
        clashes = Database().get_events_in_date_range(start_dt, end_dt, EventType.FIXED)
        if len(clashes) > 0:
            print(f"This event would clash with the following fixed events:")
            for clash in clashes:
                print(f"\t{clash.summary}")
            valid = False
            while not valid:
                cont = input("Do you want to continue? [y/N] ")
                if cont.lower() == 'n':
                    sys.exit(0)
                elif cont.lower() != 'y':
                    print('Invalid input - please try again')
                else:
                    valid = True
        """

        #Create and return FixedEvent
        return FixedEvent(summary, start_dt, end_dt)


class FlexibleEventBuilder(EventBuilder):
    """
    Builder class for flexible events
    """

    def create_flexible_event(self, valid_start_time_str: str, valid_end_time_str: str, duration: int, summary: str) -> FlexibleEvent:
        """
        Creates a flexible event from the input parameters
        :param date_str: String representation of the event date
        :param valid_start_time_str: String representation of the start of the valid time range
        :param valid_end_time_str: String representation of the end of the valid time range
        :param duration: Duration of the flexible event
        :param summary: Event summary
        :return: FlexibleEvent object containing event information provided in input args
        """

        if not summary or summary == '':
            raise ValueError("Summary cannot be empty")

        #Generate valid timerange datetimes from the valid start and end dates/times
        try:
            valid_start_dt = datetime.fromisoformat(valid_start_time_str)
            valid_end_dt = datetime.fromisoformat(valid_end_time_str)
            #valid_start_dt, valid_end_dt = self._generate_dts(date_str, valid_start_time_str, valid_end_time_str)
        except ValueError as e:
            print(e)
            sys.exit(1)


        # Fetch list of all events in the valid window in chronological order
        clashes = Database().get_events_in_date_range(valid_start_dt, valid_end_dt, EventType.ALL)

        try:
            slot_finder = FlexSlotFinder(valid_start_dt, valid_end_dt, duration)
        except ValueError as e:
            print(e)
            sys.exit(1)

        start_dt, end_dt = slot_finder.find_valid_slot(clashes)

        if not slot_finder.no_clashes:
            print("No valid time slot can be found for this event.")
            sys.exit(1)

        #Create FlexibleEvent from args (event will start at valid_start_dt and last duration minutes)
        return FlexibleEvent(summary, start_dt, end_dt, valid_start_dt, valid_end_dt)


class FlexSlotFinder:
    """
    Finds valid spaces for flexible events given the start and end valid ranges
    """
    def __init__(self, valid_start_dt: datetime, valid_end_dt: datetime, duration: int):
        if not valid_start_dt < valid_end_dt:
            raise ValueError("Start time must be before end time")

        if (valid_end_dt - valid_start_dt).total_seconds() / 60 < duration:
            raise ValueError("Duration cannot be longer than the valid range of the event")

        self.valid_start_dt = valid_start_dt
        self.valid_end_dt = valid_end_dt
        self.duration = duration
        self.no_clashes = False
        self.start_dt = None
        self.end_dt = None

    def find_valid_slot(self, events: List[Event]) -> Tuple[datetime, datetime]:

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
    """
    Stores local timezone information
    """
    def __init__(self):
        self.timezone = self.local_tz()

    @staticmethod
    def local_tz() -> str:
        """
        :return: System timezone
        """

        #Get local timezone from system
        try:
            return get_localzone_name()
        except Exception as e:
            print(f"Error getting system timezone: {e}")
            sys.exit(1)


class Database(metaclass=Singleton):

    def __init__(self, db_name=os.path.join(WORKING_DIR, "events.db")) -> None:
        self.db_name = db_name
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
        """
        Updates event last modified timestamp in db
        :param event:
        :return:
        """
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
                       UPDATE events
                       SET last_updated = ?
                       WHERE google_id = ?
                       ''', (datetime.now().isoformat(), event.google_id))
        conn.commit()
        conn.close()

    def event_status(self, gc_event: Event) -> EventStatus:
        """
        Checks whether an event has been added or modified (compared to the db)
        :param gc_event: Event to check status of
        :return: EventStatus object with status of event
        """

        #Connect to db
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Check if event with same google_id exists
        cursor.execute('''
                       SELECT summary, event_start_dt, event_end_dt
                       FROM events
                       WHERE google_id = ?
                       LIMIT 1
                       ''', (gc_event.google_id,))

        event_status = EventStatus.NEW
        db_event = cursor.fetchone()
        conn.close()

        #Check if any metadata for the event has changed
        if db_event:
            if db_event[0] != gc_event.summary or db_event[1] != gc_event.start_dt.isoformat() or db_event[2] != gc_event.end_dt.isoformat():
                event_status = EventStatus.MODIFIED
            else:
                event_status = EventStatus.UNCHANGED
            self.__update_timestamp(gc_event)

        return event_status

    def add_event(self, event: Event) -> int:
        """
        Adds an event to the database
        :param event: Event to add to db
        :return: New eventID if successful, -1 otherwise
        """

        # If the event is a duplicate, return False
        if self.event_status(event) != EventStatus.NEW:
            raise ValueError(f"Event {event.summary} already exists in the database")

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


    def del_event(self, event: Event) -> None:
        """
        Deletes an event from the database
        :param event: Event to be deleted
        :return: None
        """

        #Check that event exists in the DB
        if self.event_status(event) == EventStatus.NEW:
            raise ValueError(f"Event {event.summary} does not exist in the database")

        #Delete event
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
        DELETE FROM events
            WHERE google_id = ?
        ''', (event.google_id,))

        conn.commit()
        conn.close()
        print(f"Event {event.summary} deleted from database successfully")

    @staticmethod
    def __create_event_from_db_query(db_query:List[tuple]) -> List[Event]:
        events = []
        for event in db_query:
            if event[1] == 0:
                events.append(
                    FixedEvent(event[0], datetime.fromisoformat(event[2]), datetime.fromisoformat(event[3]), event[6]))
            else:
                events.append(
                    FlexibleEvent(event[0], datetime.fromisoformat(event[2]), datetime.fromisoformat(event[3]),
                                  datetime.fromisoformat(event[4]), datetime.fromisoformat(event[5]), event[6]))

        return events

    def get_upcoming_events(self, num_events: int = 50, event_type: EventType = EventType.ALL, order_by: OrderBy = OrderBy.START) -> List[Event]:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # If event type is all, the is_flexible filter is not needed
        if event_type == EventType.ALL:
            cursor.execute(f"""
                                   SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                                   FROM events
                                   WHERE event_end_dt >= ?
                                   ORDER BY {order_by.value}
                                   LIMIT ?""",
                           (datetime.now().isoformat(), num_events,))

        else:
            cursor.execute(f"""
                                   SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                                   FROM events
                                   WHERE (is_flexible = ?)
                                    AND (event_end_dt >= ?)
                                   ORDER BY {order_by.value}
                                   LIMIT ?""",
                           (event_type.value, datetime.now().isoformat(), num_events,))

        # Create a list of events from the DB query results
        events = self.__create_event_from_db_query(cursor.fetchall())
        conn.close()

        return events

    def get_events_in_date_range(self, from_dt: datetime, to_dt: datetime, event_type: EventType = EventType.ALL, order_by: OrderBy = OrderBy.START) -> List[Event]:
        """
        Returns all events within the given time range
        :param from_dt: Start time
        :param to_dt: End time
        :param event_type: Types of events to return (Fixed, Flexible or all)
        :param order_by: Order by (start times or end times)
        :return: List of events in range
        """

        if not from_dt < to_dt:
            raise ValueError("Start date/time must be before end date/time")

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        #If event type is all, the is_flexible filter is not needed
        if event_type == EventType.ALL:
            cursor.execute(f"""
                           SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                           FROM events
                           WHERE (event_start_dt BETWEEN ? AND ?)
                            OR (? BETWEEN event_start_dt AND event_end_dt)
                            OR (? BETWEEN event_start_dt AND event_end_dt)
                           ORDER BY {order_by.value}""",
                           (from_dt.isoformat(), to_dt.isoformat(), from_dt.isoformat(), to_dt.isoformat()))

        else:
            cursor.execute(f"""
                           SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                           FROM events
                           WHERE (is_flexible = ?)
                            AND (
                                (event_start_dt BETWEEN ? AND ?)
                                OR (? BETWEEN event_start_dt AND event_end_dt)
                                OR (? BETWEEN event_start_dt AND event_end_dt)
                            )
                           ORDER BY {order_by.value}""",
                           (event_type.value, from_dt.isoformat(), to_dt.isoformat(), from_dt.isoformat(), to_dt.isoformat()))

        #Create a list of events from the DB query results
        events = self.__create_event_from_db_query(cursor.fetchall())
        conn.close()

        return events

    def get_event_by_google_id(self, google_id: str) -> Event:
        """
        Returns event with the given google_id
        :param google_id: Google ID of event to fetch
        :return: Event with given google_id
        """

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT summary, is_flexible, event_start_dt, event_end_dt, valid_start_dt, valid_end_dt, google_id
                       FROM events
                       WHERE google_id = ?
                       LIMIT 1
                       ''', (google_id,))

        event_data = cursor.fetchone()
        conn.close()

        if not event_data:
            raise ValueError(f"No event found with google_id {google_id}")

        if event_data[1] == 0:
            return FixedEvent(event_data[0], datetime.fromisoformat(event_data[2]), datetime.fromisoformat(event_data[3]), event_data[6])
        else:
            return FlexibleEvent(
                event_data[0], datetime.fromisoformat(event_data[2]), datetime.fromisoformat(event_data[3]),
                datetime.fromisoformat(event_data[4]), datetime.fromisoformat(event_data[5]), event_data[6])


    def edit_event(self, event: Event, update_valid_window: bool = False) -> None:
        """
        Modifies an event's db metadata with that of the event passed as the argument
        :param event: Event with the updated metadata
        :param update_valid_window: Whether to also update the valid window of the event (for flexible events)
        :return: None
        """

        #Check if the event has been modified
        if self.event_status(event) != EventStatus.MODIFIED:
            raise ValueError(f"Event {event.summary} has not been modified")

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        #Update the event with new data
        cursor.execute('''
                       UPDATE events
                       SET summary = ?,
                           event_start_dt = ?,
                           event_end_dt   = ?,
                           duration = ?,
                           timezone = ?,
                           last_updated = ?
                       WHERE google_id = ?
       ''', (event.summary,
                        event.start_dt.isoformat(),
                        event.end_dt.isoformat(),
                        event.duration,
                         Timezone().timezone,
                        datetime.now().isoformat(),
                        event.google_id),)

        #TODO: ensure updates to start/end time that lie outside the valid window also update the valid window accordingly
        if update_valid_window:
            cursor.execute('''
            UPDATE events
            SET valid_start_dt = ?,
                valid_end_dt = ?
            WHERE google_id = ?
                ''', (event.valid_start_dt.isoformat(),
                                event.valid_end_dt.isoformat(),
                                event.google_id),)

        conn.commit()
        conn.close()


    def update_google_id(self, db_id: int, google_id: str) -> None:
        """
        Updates the google_id for an event (used for creating new events that do not have a google_id yet)
        :param db_id: Event ID in the database
        :param google_id: Google ID to add to event
        :return: None
        """
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
        self.scopes = ["https://www.googleapis.com/auth/calendar"]
        self.creds = self.__authenticate()
        self.calendar_id = "primary"

    def __authenticate(self):
        # Creates the json access and refresh tokens to authenticate user to the application
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file(os.path.join(WORKING_DIR, "token.json"), self.scopes)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Failed to refresh token: {e}")
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    os.path.join(WORKING_DIR, "credentials.json"), self.scopes
                )
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open("token.json", "w") as token:
                token.write(creds.to_json())

        return creds

    @staticmethod
    def __to_event_object(event_json) -> FixedEvent:
        """
        Converts event from API response to an event object
        :param event_json: event from Google API
        :return: Event object
        """
        summary = event_json['summary']
        start_str = event_json["start"].get("dateTime", event_json["start"].get("date"))
        end_str = event_json["end"].get("dateTime", event_json["end"].get("date"))
        event_id = event_json["id"]

        return FixedEvent(summary, datetime.fromisoformat(start_str), datetime.fromisoformat(end_str), event_id)


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

    def __get_events_json(self, start_dt: datetime = datetime.now(), end_dt: datetime = None, get_deleted=False, in_range: bool = False, max_results: int = 50) -> List[dict]:
        """
        Fetches JSON of events in a given time range from Google Calendar API
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: List of events in JSON format
        """

        start_formatted = start_dt.isoformat() + 'Z'
        end_formatted = None

        if in_range:
            if not end_dt:
                raise ValueError("End datetime must be provided if in_range is True")

            end_formatted = end_dt.isoformat() + 'Z'

        try:
            service = build("calendar", "v3", credentials=self.creds)

            # Send request to API to return list of events on chosen day
            events_result = service.events().list(
                calendarId=GoogleCalendar().calendar_id,
                timeMin=start_formatted,
                timeMax=end_formatted,
                maxResults=max_results,
                singleEvents=True,
                showDeleted=get_deleted,
                orderBy='startTime'
            ).execute()

            # Generate list from JSON return body
            events_json = events_result.get('items', [])
            return events_json

        except HttpError as error:
            print(f"An HTTP error occurred: {error}")
            sys.exit(1)

    def get_events(self, start_dt: datetime = datetime.now(), end_dt: datetime = None, in_range: bool = False) -> tuple[List[FixedEvent], List[FixedEvent]]:
        """
        Returns list of current and deleted events in a given time range from the Google Calendar
        :param in_range: Whether to get events in a specific time range
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: Tuple: List of current events, List of deleted events
        """

        if in_range and not start_dt < end_dt:
            raise ValueError("Start date/time must be before end date/time")

        #Get list of events from API
        events_json = self.__get_events_json(start_dt, end_dt, get_deleted=True, in_range=in_range)

        current_events = []
        deleted_events = []
        #Convert events_json to Event objects
        for event in events_json:
            if event['status'] == 'cancelled':
                deleted_events.append(self.__to_event_object(event))
            else:
                current_events.append(self.__to_event_object(event))
        return current_events, deleted_events

    def event_exists(self, event_id: str) -> bool:
        """
        Checks if an event with the given event_id exists in the Google Calendar.
        :param event_id: The Google Calendar event ID.
        :return: True if the event exists, False otherwise.
        """
        try:
            service = build("calendar", "v3", credentials=self.creds)
            service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
            return True
        except HttpError as error:
            if error.resp.status == 404:
                return False
            else:
                raise

    def edit_event(self, event: Event) -> None:
        """
        Update details of event in Google Calendar
        :param event: Event with new details
        :return: None
        """
        if not self.event_exists(event.google_id):
            raise ValueError(f"Event {event.summary} does not exist in Google Calendar")


        service = build("calendar", "v3", credentials=self.creds)

        #Patch Request with new data
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

    def delete_event(self, event: Event) -> None:
        """
        Deletes an event from the Google Calendar
        :param event: Event to delete
        :return: None
        """
        if not self.event_exists(event.google_id):
            raise ValueError(f"Event {event.summary} does not exist in Google Calendar")

        service = build("calendar", "v3", credentials=self.creds)

        service.events().delete(
            calendarId=self.calendar_id,
            eventId=event.google_id
        ).execute()

        print(f"Event {event.summary} deleted from Google Calendar")

class EventManager:
    """
    Class to manage alignment of events in Google calendar and database
    """
    @staticmethod
    def sync_gc_to_db(in_range: bool = False, start_dt: datetime = datetime.now(), end_dt: datetime = None) -> None:
        """
        Adds existing events from the Google calendar in a given time range to the DB
        :param in_range: Whether to sync events in a specific time range
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: None
        """
        # Get list of all events on day from Google calendar
        cur_events, del_events = GoogleCalendar().get_events(start_dt, end_dt, in_range=in_range)

        if not cur_events and not del_events:
            raise ValueError("No events found in Google Calendar in the given time range")

        #Sync to DB
        for event in cur_events:
            if Database().event_status(event) == EventStatus.NEW:
                Database().add_event(event)
            elif Database().event_status(event) == EventStatus.MODIFIED:
                #find valid start and end times, update first to prevent overwriting
                Database().edit_event(event)

        for event in del_events:
            try:
                Database().del_event(event)
            except ValueError as error:
                print(error)

    @staticmethod
    def submit_event(event) -> None:
        """
        Adds an event to the database and google calendar
        :param event: Event to add to calendar and db
        :return: None
        """
        # Add event to database, return whether it was added successfully
        try:
            db_id = Database().add_event(event)
        except ValueError as e:
            print(e)
            sys.exit(1)
        #If event was added to the DB successfully, add to the Google Calendar

        google_id = GoogleCalendar().add_event(event)
        Database().update_google_id(db_id, google_id)
        print(f"Submitted event {event.summary}")

    @staticmethod
    def edit_event(event: Event, update_valid_window: bool = False) -> None:
        Database().edit_event(event, update_valid_window=update_valid_window)
        GoogleCalendar().edit_event(event)

    @staticmethod
    def delete_event(event: Event) -> None:
        Database().del_event(event)
        GoogleCalendar().delete_event(event)


class DateTimeConverter:
    """
    Handles data type conversion of times
    """
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
        """
        Converts string input in the format dd-mm-YYYY to a datetime.datetime object
        :param date_str: string representation of the date (in dd-mm-YYYY format)
        :return: datetime object representation of the date
        """
        try:
            return datetime.strptime(date_str, "%d-%m-%Y")
        except ValueError as e:
            print(f"Invalid date format: {e}")
            sys.exit(1)

    @staticmethod
    def get_cur_midnight(dt: datetime) -> datetime:
        """
        Returns 00:00 of current day (as datetime object)
        :param dt: current day
        :return: midnight of the current day
        """
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def get_next_midnight(dt: datetime) -> datetime:
        """
        Returns 00:00 of next day (as datetime object)
        :param dt: current day
        :return: midnight of the next day
        """
        dt_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt_midnight + timedelta(days=1)

class FlexEventOptimiser:
    """
    Handles the rearrangement of flex events when events are added/modified
    """
    def __init__(self, precision = 15) -> None:
        self.mins_in_day = 1440
        self.precision = precision
        self.num_slots = self.mins_in_day // self.precision

    def convert_time_to_slot(self, dt: datetime):
        mins_after_midnight = dt.hour * 60 + dt.minute
        return mins_after_midnight // self.precision

    def convert_slot_to_time(self, slot: int) -> datetime.time:
        total_mins = slot * self.precision
        hour = total_mins // 60
        minute = total_mins % 60
        return hour, minute

    def preprocess_events(self, events_list: List[Event]) -> dict:
        processed_events = {}
        #Convert event start time, end time, and duration into time slots and store in dictionary of events
        for event in events_list:
            start_slot = self.convert_time_to_slot(event.valid_start_dt)
            end_slot = self.convert_time_to_slot(event.valid_end_dt)
            duration_slot = event.duration // self.precision
            processed_events[event] = (duration_slot, start_slot, end_slot)

        return processed_events

    def run_ILP_optimiser(self, dt: datetime):
        # Get current and next midnight (the start and end time for the day we are optimising)
        cur_midnight = DateTimeConverter().get_cur_midnight(dt)
        next_midnight = DateTimeConverter().get_next_midnight(dt)

        events_list = Database().get_events_in_date_range(cur_midnight, next_midnight, EventType.ALL, OrderBy.START)

        processed_events = self.preprocess_events(events_list)


        #Create minimisation problem
        model = pulp.LpProblem("Minimise_Event_Clashes", pulp.LpMinimize)

        #Set up decision variables
        #x[i,t] = 1 if event i starts at time slot t, 0 otherwise
        x = pulp.LpVariable.dicts(
            "x",
            ((i, t) for i in processed_events for t in range(self.num_slots)),
            cat='Binary'
        )

        #o[i,j] = 1 if event i overlaps with event j, 0 otherwise
        o = pulp.LpVariable.dicts(
            "o",
            ((i, j) for i in processed_events for j in processed_events if i.google_id < j.google_id),
            cat='Binary'
        )

        #Constraints
        #Each event should be scheduled exactly once within its valid time range
        for i, data in processed_events.items():
            duration_slot, start_slot, end_slot = data
            model += (pulp.lpSum(x[i, t] for t in range(start_slot, end_slot - duration_slot + 1)) == 1,
                      f"Event_{i}_scheduled_once")

        #No overlapping events
        for i, data_i in processed_events.items():
            for j, data_j in processed_events.items():
                if i.google_id >= j.google_id:
                    continue

                duration_i, start_i, end_i = data_i
                duration_j, start_j, end_j = data_j

                for t_i in range(start_i, end_i + 1):
                    for t_j in range(start_j, end_j + 1):
                        if (t_i < t_j + duration_j) and (t_j < t_i + duration_i):
                            model += (o[i, j] >= x[i, t_i] + x[j, t_j] -1,
                                      f"Overlap_{i}_{j}_at_{t_i}_{t_j}")

        #Objective function: Minimise total overlaps
        model += pulp.lpSum(o[i, j] for i, j in o), "Minimise_Total_Overlaps"

        # solve the ILP model
        solver = pulp.PULP_CBC_CMD()
        model.solve(solver)

        print("Status:", pulp.LpStatus[model.status])
        print("Total overlaps:", pulp.value(model.objective))

        #return list of events with their assigned optimal start times
        for i in processed_events:
            for t in range(self.num_slots):
                if pulp.value(x[i, t]) == 1:
                    hour, minute = self.convert_slot_to_time(t)
                    duration = i.duration
                    print(f"Event {i.summary} starts at slot {t} and ends at slot {t + processed_events[i][0]}")
                    i.start_dt = i.start_dt.replace(hour=hour, minute=minute)
                    print(f"Event {i.summary} starts at {i.start_dt.hour:02}:{i.start_dt.minute:02}")
                    i.end_dt = i.start_dt + timedelta(minutes=duration)
                    print(f"Event {i.summary} ends at {i.end_dt.hour:02}:{i.end_dt.minute:02}")


        for i, j in o:
            if pulp.value(o[i, j]) == 1:
                print(f"Event {i.summary} overlaps with event {j.summary}")


        return list(processed_events.keys())

def main():
    pass

if __name__ == "__main__":
    main()
