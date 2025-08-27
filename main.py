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

        return start_dt, end_dt


class FixedEventBuilder(EventBuilder):
    """
    Builder class for fixed events
    """

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

        clashes = Database().get_events(start_dt, end_dt, EventType.FIXED)
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


        #Create and return FixedEvent
        return FixedEvent(summary, start_dt, end_dt)


class FlexibleEventBuilder(EventBuilder):
    """
    Builder class for flexible events
    """

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

        # Fetch list of all events in the valid window in chronological order
        clashes = Database().get_events(valid_start_dt, valid_end_dt, EventType.ALL)

        slot_finder = FlexSlotFinder(valid_start_dt, valid_end_dt, duration)
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


    def del_event(self, event: Event) -> None:
        """
        Deletes an event from the database
        :param event: Event to be deleted
        :return: None
        """

        #Check that event exists in the DB
        if self.event_status(event) == EventStatus.NEW:
            print(f"Event {event.summary} does not exist in the database")
            return

        #Delete event
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
        DELETE FROM events
            WHERE google_id = ?
        ''', event.google_id)

        conn.commit()
        conn.close()
        print(f"Event {event.summary} deleted from database successfully")

    def get_events(self, from_dt: datetime, to_dt: datetime, event_type: EventType = EventType.ALL, order_by: OrderBy = OrderBy.START) -> List[Event]:
        """
        Returns all events within the given time range
        :param from_dt: Start time
        :param to_dt: End time
        :param event_type: Types of events to return (Fixed, Flexible or all)
        :param order_by: Order by (start times or end times)
        :return: List of events in range
        """
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
                            AND (event_start_dt BETWEEN ? AND ?)
                            OR (? BETWEEN event_start_dt AND event_end_dt)
                            OR (? BETWEEN event_start_dt AND event_end_dt)
                           ORDER BY {order_by.value}""",
                           (event_type.value, from_dt.isoformat(), to_dt.isoformat(), from_dt.isoformat(), to_dt.isoformat()))

        #Create a list of events from the DB query results
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

    def edit_event(self, event: Event) -> None:
        """
        Modifies an event's db metadata with that of the event passed as the argument
        :param event: Event with the updated metadata
        :return: None
        """

        #Check if the event has been modified
        if self.event_status(event) != EventStatus.MODIFIED:
            print(f"Event {event.summary} has not been modified")

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        #Update the event with new data
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

    def __get_events_json(self, start_dt: datetime, end_dt: datetime, get_deleted=False) -> List[dict]:
        """
        Fetches JSON of events in a given time range from Google Calendar API
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: List of events in JSON format
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
                showDeleted=get_deleted,
                orderBy='startTime'
            ).execute()

            # Generate list from JSON return body
            events_json = events_result.get('items', [])
            return events_json

        except HttpError as error:
            print(f"An HTTP error occurred: {error}")
            sys.exit(1)

    def get_events(self, start_dt: datetime, end_dt: datetime) -> tuple[List[FixedEvent], List[FixedEvent]]:
        """
        Returns list of current and deleted events in a given time range from the Google Calendar
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: Tuple: List of current events, List of deleted events
        """

        #Get list of events from API
        events_json = self.__get_events_json(start_dt, end_dt, get_deleted=True)

        current_events = []
        deleted_events = []
        #Convert events_json to Event objects
        for event in events_json:
            if event['status'] == 'cancelled':
                deleted_events.append(self.__to_event_object(event))
            else:
                current_events.append(self.__to_event_object(event))
        return current_events, deleted_events


    def edit_event(self, event: Event) -> None:
        """
        Update details of event in Google Calendar
        :param event: Event with new details
        :return: None
        """

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

class EventManager:
    """
    Class to manage alignment of events in Google calendar and database
    """
    @staticmethod
    def sync_gc_to_db(start_dt: datetime, end_dt: datetime) -> None:
        """
        Adds existing events from the Google calendar in a given time range to the DB
        :param start_dt: Start datetime
        :param end_dt: End datetime
        :return: None
        """
        # Get list of all events on day from Google calendar
        cur_events, del_events = GoogleCalendar().get_events(start_dt, end_dt)

        #Sync to DB
        for event in cur_events:
            if Database().event_status(event) == EventStatus.NEW:
                Database().add_event(event)
            elif Database().event_status(event) == EventStatus.MODIFIED:
                Database().edit_event(event)

        for event in del_events:
            Database().del_event(event)

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

    @staticmethod
    def edit_event(event: Event) -> None:
        Database().edit_event(event)
        GoogleCalendar().edit_event(event)


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
    @staticmethod
    def move_events(flex_events, fixed_events) -> Tuple[List[FlexibleEvent], List[FlexibleEvent]]:
        """
        Moves flex events into valid slots (if no valid slots exist, a list of invalid events will be returned)
        :param flex_events: List of flex events to be rearranged
        :param fixed_events: List of fixed events to rearrange around
        :return: Tuple: List of valid events after rearrangement, List of invalid events after rearrangement
        """
        invalid_events = []
        valid_events = []

        #Find a valid slot for each event
        for event in flex_events:
            slot_finder = FlexSlotFinder(event.valid_start_dt, event.valid_end_dt, event.duration)
            new_start_dt, new_end_dt = slot_finder.find_valid_slot(fixed_events)
            updated_event = FlexibleEvent(event.summary, new_start_dt, new_end_dt, event.valid_start_dt,
                                          event.valid_end_dt, event.google_id)

            #If a valid slot can be found without clashes, add to valid events list and to list of events to find slot around
            if slot_finder.no_clashes:
                valid_events.append(updated_event)
                fixed_events.append(FixedEvent(updated_event.summary, updated_event.start_dt, updated_event.end_dt))
                fixed_events.sort(key=lambda x: x.start_dt)

            #Else, add to invalid events list
            else:
                invalid_events.append(updated_event)

        return valid_events, invalid_events


    def optimise_flex_events(self, dt: datetime) -> None:
        """
        Finds optimal slot for flex events on a given day
        :param dt: Day to optimise flex events for
        :return: None
        """

        #Get current and next midnight (the start and end time for the day we are optimising)
        cur_midnight = DateTimeConverter().get_cur_midnight(dt)
        next_midnight = DateTimeConverter().get_next_midnight(dt)

        #Get list of all fixed events on day
        fixed_events_st = Database().get_events(cur_midnight, next_midnight, EventType.FIXED)
        fixed_events_et = copy.deepcopy(fixed_events_st)

        #Get 2 lists of all flex events on day, one ordered by start time, one ordered by end time
        flex_events_st = Database().get_events(cur_midnight, next_midnight, EventType.FLEXIBLE, OrderBy.START)
        flex_events_et = Database().get_events(cur_midnight, next_midnight, EventType.FLEXIBLE, OrderBy.END)

        #Move flex events to valid slots for each list
        valid_events_st, invalid_events_st = self.move_events(flex_events_st, fixed_events_st)
        valid_events_et, invalid_events_et = self.move_events(flex_events_et, fixed_events_et)


        #For the list with more valid events, update the DB and GC with the new event times
        em = EventManager()
        if len(valid_events_st) > len(valid_events_et):
            if len(invalid_events_st) > 0:
                print(f"Invalid events found: {invalid_events_st}")

            for event in valid_events_st:
                em.edit_event(event)
        else:
            if len(invalid_events_st) > 0:
                print(f"Invalid events found: {invalid_events_et}")

            for event in valid_events_et:
                em.edit_event(event)


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
                                         "18:00",
                                         "21:00",
                                         30,
                                         "Test Flexible event 4")
    #print(new_event)

    em.submit_event(new_event)
    """
    #new_event.submit_event(creds, db_name="events.db")

    FlexEventOptimiser().optimise_flex_events(dt)



if __name__ == "__main__":
    main()
    #create_table()
