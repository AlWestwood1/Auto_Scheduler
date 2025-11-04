import string
import unittest
from unittest.mock import patch, MagicMock
import random
from tzlocal import get_localzone_name
import os
import sqlite3

from googleapiclient.errors import HttpError
import scheduler
from datetime import datetime, timedelta
import zoneinfo

class RandomEventBuilder:
    def __init__(self):
        self.tz = zoneinfo.ZoneInfo("Europe/London")


    def __generate_start_end_dts(self):
        minute = random.randint(0, 59)
        hour = random.randint(0, 23)
        day = random.randint(1, 28)
        month = random.randint(1, 12)
        year = random.randint(2022, 2030)
        duration = random.randint(15, 60)

        start_dt = datetime(year, month, day, hour, minute, tzinfo=self.tz)
        end_dt = start_dt + timedelta(minutes=duration)

        return start_dt, end_dt

    @staticmethod
    def __generate_valid_start_end_dts(start_dt, end_dt):
        valid_start_dt = start_dt + timedelta(minutes=random.randint(-60, 0))
        valid_end_dt = end_dt + timedelta(minutes=random.randint(0, 60))
        return valid_start_dt, valid_end_dt

    @staticmethod
    def generate_random_summary():
        return ''.join(random.choice(string.ascii_lowercase) for _ in range(random.randint(5, 10)))

    @staticmethod
    def generate_random_google_id():
        return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(26))

    def generate_fixed_event(self):
        start_dt, end_dt = self.__generate_start_end_dts()
        summary = self.generate_random_summary()
        google_id = self.generate_random_google_id()
        return scheduler.FixedEvent(summary, start_dt, end_dt, google_id)


    def generate_flexible_event(self):
        start_dt, end_dt = self.__generate_start_end_dts()
        valid_start_dt, valid_end_dt = self.__generate_valid_start_end_dts(start_dt, end_dt)
        summary = self.generate_random_summary()
        google_id = self.generate_random_google_id()
        return scheduler.FlexibleEvent(summary, start_dt, end_dt, valid_start_dt, valid_end_dt, google_id)

class TestFixedEvent(unittest.TestCase):
    def setUp(self):
        self.start_dt =  datetime(2025, 9, 1, 16, 0, tzinfo=zoneinfo.ZoneInfo("Europe/London"))
        self.end_dt = datetime(2025, 9, 1, 17, 0, tzinfo=zoneinfo.ZoneInfo("Europe/London"))
        self.fixed_e1 = scheduler.FixedEvent("Test Fixed Event 1", self.start_dt, self.end_dt, '1a2b3c')

    def test_init(self):
        self.assertEqual(self.fixed_e1.summary, 'Test Fixed Event 1')
        self.assertEqual(self.fixed_e1.start_dt, self.start_dt)
        self.assertEqual(self.fixed_e1.end_dt, self.end_dt)
        self.assertEqual(self.fixed_e1.is_flexible, 0)
        self.assertEqual(self.fixed_e1.valid_start_dt, self.start_dt)
        self.assertEqual(self.fixed_e1.valid_end_dt, self.end_dt)

    def test_duration(self):
        self.assertEqual(self.fixed_e1.duration, 60)

    def test_get_start_end_dt(self):
        self.assertEqual(self.fixed_e1.get_start_end_dt(), (self.start_dt, self.end_dt))


class TestFlexibleEvent(unittest.TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo("Europe/London")
        self.start_dt = datetime(2025, 8, 2, 16, 0, tzinfo=self.tz)
        self.end_dt = datetime(2025, 8, 2, 16, 30, tzinfo=self.tz)
        self.valid_start_dt = datetime(2025, 8, 2, 16, 0, tzinfo=self.tz)
        self.valid_end_dt = datetime(2025, 8, 2, 22, 0, tzinfo=self.tz)
        self.flex_e1 = scheduler.FlexibleEvent("Test Flex Event 1", self.start_dt, self.end_dt, self.valid_start_dt, self.valid_end_dt)

    def test_init(self):
        self.assertEqual(self.flex_e1.summary, 'Test Flex Event 1')
        self.assertEqual(self.flex_e1.start_dt, self.start_dt)
        self.assertEqual(self.flex_e1.end_dt, self.end_dt)
        self.assertEqual(self.flex_e1.is_flexible, 1)
        self.assertEqual(self.flex_e1.valid_start_dt, self.valid_start_dt)
        self.assertEqual(self.flex_e1.valid_end_dt, self.valid_end_dt)

    def test_duration(self):
        self.assertEqual(self.flex_e1.duration, 30)

    def test_get_start_end_dt(self):
        self.assertEqual(self.flex_e1.get_start_end_dt(), (self.start_dt, self.end_dt))

    def test_get_valid_range(self):
        self.assertEqual(self.flex_e1.get_valid_range(), (self.valid_start_dt, self.valid_end_dt))


class TestEventBuilder(unittest.TestCase):
    def setUp(self):
        self.eb = scheduler.EventBuilder()

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_generate_dts_fails_wrong_date_format(self, mock_exit):
        invalid_date_formats = ["05.08.2025",
                                "05/08/2025",
                                "2025-05-08",
                                "cat",
                                "12345",
                                "65-08-2025",
                                "12-70-2025",
                                "05-08-25"]

        for date in invalid_date_formats:
            with self.assertRaises(SystemExit):
                self.eb._generate_dts(date, "12:00", "11:00")

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_generate_dts_fails_wrong_start_time_format(self, mock_exit):
        invalid_time_formats = ["12-00",
                                "12:00:01",
                                "12.00",
                                "abc",
                                "",
                                "28:00",
                                "12:76"]

        for start_time in invalid_time_formats:
            with self.assertRaises(SystemExit):
                self.eb._generate_dts("05-08-2025", start_time, "23:00")

        self.assertEqual(mock_exit.call_count, len(invalid_time_formats))
        mock_exit.assert_called_with(1)

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_generate_dts_fails_wrong_end_time_format(self, mock_exit):
        invalid_time_formats = ["14-00",
                                "12:00:01",
                                "12.00",
                                "abc",
                                "",
                                "28:00",
                                "12:76"]

        for end_time in invalid_time_formats:
            with self.assertRaises(SystemExit):
                self.eb._generate_dts("05-08-2025", "09:00", end_time)

        self.assertEqual(mock_exit.call_count, len(invalid_time_formats))
        mock_exit.assert_called_with(1)

    def test_generate_dts_fail_end_dt_before_start_dt(self):
        date_str = "05-08-2025"
        with self.assertRaises(ValueError):
            self.eb._generate_dts(date_str, "12:00", "11:00")

        with self.assertRaises(ValueError):
            self.eb._generate_dts(date_str, "23:59", "00:00")

    def test_generate_dts_success(self):
        date_str = "05-08-2025"
        tz = zoneinfo.ZoneInfo(get_localzone_name())
        self.assertEqual(self.eb._generate_dts(date_str, "12:00", "13:00"),
                         (datetime(2025, 8, 5, 12, 0, tzinfo=tz), datetime(2025, 8, 5, 13, 0, tzinfo=tz)))

class TestFixedEventBuilder(unittest.TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo(get_localzone_name())
        self.events_no_clash = []

        self.events_clash = [scheduler.FixedEvent("Event clash 1",
                                                  datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                                  datetime(2025, 8, 5, 18, 0, tzinfo=self.tz)),
                             scheduler.FixedEvent("Event clash 2",
                                                  datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                                  datetime(2025, 8, 5, 20, 0, tzinfo=self.tz))]

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_fixed_eb_fails_end_dt_before_start_dt(self, mock_exit):
        fixed_eb = scheduler.FixedEventBuilder()
        with self.assertRaises(SystemExit):
            fixed_eb.create_fixed_event("05-08-2025", "18:00", "17:00", "Test Fixed_EB Fail")
        mock_exit.assert_called_once_with(1)

    def __event_clash_test(self, event):
        self.assertIsInstance(event, scheduler.FixedEvent)
        self.assertEqual(event.summary, "Test Fixed EB")
        self.assertEqual(event.start_dt, datetime(2025, 8, 5, 14, 0, tzinfo=self.tz))
        self.assertEqual(event.end_dt, datetime(2025, 8, 5, 15, 0, tzinfo=self.tz))

    @patch("scheduler.Database.get_events")
    def test_fixed_event_creation_no_clash(self, mock_events):
        mock_events.return_value = self.events_no_clash
        fixed_eb = scheduler.FixedEventBuilder()

        event = fixed_eb.create_fixed_event("05-08-2025","14:00", "15:00", "Test Fixed EB")
        self.__event_clash_test(event)


    @patch("scheduler.sys.exit", side_effect=SystemExit)
    @patch("builtins.input", return_value='n')
    @patch("scheduler.Database.get_events")
    def test_fixed_event_creation_with_clash_user_continues(self, mock_events, mock_input, mock_exit):
        mock_events.return_value = self.events_clash
        fixed_eb = scheduler.FixedEventBuilder()
        with self.assertRaises(SystemExit):
            fixed_eb.create_fixed_event("05-08-2025", "14:00", "15:00", "Test Fixed EB")
        mock_exit.assert_called_once_with(0)

    def test_fixed_event_creation_fails_no_summary(self):
        fixed_eb = scheduler.FixedEventBuilder()
        with self.assertRaises(ValueError):
            fixed_eb.create_fixed_event("05-08-2025", "14:00", "15:00", "")



class TestFlexibleEventBuilder(unittest.TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo(get_localzone_name())

        self.events_clash = [scheduler.FixedEvent("Event clash 1",
                                                  datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                                  datetime(2025, 8, 5, 18, 0, tzinfo=self.tz)),
                             scheduler.FixedEvent("Event clash 2",
                                                  datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                                  datetime(2025, 8, 5, 20, 0, tzinfo=self.tz))]

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_flex_eb_fails_end_dt_before_start_dt(self, mock_exit):
        flex_eb = scheduler.FlexibleEventBuilder()
        with self.assertRaises(SystemExit):
            flex_eb.create_flexible_event("05-08-2025", "18:00", "17:00", 30, "Test Flex_EB Fail")
        mock_exit.assert_called_once_with(1)

    def test_flex_event_creation_fails_no_summary(self):
        flex_eb = scheduler.FlexibleEventBuilder()
        with self.assertRaises(ValueError):
            flex_eb.create_flexible_event("05-08-2025", "14:00", "15:00", 30, "")

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_flex_event_creation_fails_duration_longer_than_valid_range(self, mock_exit):
        flex_eb = scheduler.FlexibleEventBuilder()
        with self.assertRaises(SystemExit):
            flex_eb.create_flexible_event("05-08-2025", "14:00", "15:00", 90, "Test Flex_EB Fail")
        mock_exit.assert_called_once_with(1)


    @patch("scheduler.sys.exit", side_effect=SystemExit)
    @patch("scheduler.Database.get_events")
    def test_flex_event_creation_fails_no_valid_slot(self, mock_events, mock_exit):
        mock_events.return_value = self.events_clash
        flex_eb = scheduler.FlexibleEventBuilder()
        with self.assertRaises(SystemExit):
            flex_eb.create_flexible_event("05-08-2025", "14:00", "15:00", 30, "Test Flex_EB Fail")

        with self.assertRaises(SystemExit):
            flex_eb.create_flexible_event("05-08-2025", "11:45", "20:15", 30, "Test Flex_EB Fail")

        self.assertEqual(mock_exit.call_count, 2)
        mock_exit.assert_called_with(1)

    @patch("scheduler.Database.get_events")
    def test_flex_event_creation_successful(self, mock_events):
        mock_events.return_value = self.events_clash
        flex_eb = scheduler.FlexibleEventBuilder()
        event1 = flex_eb.create_flexible_event("05-08-2025", "09:00", "10:00", 30, "Test Flex_EB 1")
        self.assertEqual(event1.start_dt, datetime(2025, 8, 5, 9, 0, tzinfo=self.tz))
        self.assertEqual(event1.end_dt, datetime(2025, 8, 5, 9, 30, tzinfo=self.tz))
        event2 = flex_eb.create_flexible_event("05-08-2025", "11:45", "20:30", 30, "Test Flex_EB 2")
        self.assertEqual(event2.start_dt, datetime(2025, 8, 5, 20, 0, tzinfo=self.tz))
        self.assertEqual(event2.end_dt, datetime(2025, 8, 5, 20, 30, tzinfo=self.tz))

class TestFlexSlotFinder(unittest.TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo(get_localzone_name())

        self.events_clash = [scheduler.FixedEvent("Event clash 1",
                                                  datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                                  datetime(2025, 8, 5, 18, 0, tzinfo=self.tz)),
                             scheduler.FixedEvent("Event clash 2",
                                                  datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                                  datetime(2025, 8, 5, 20, 0, tzinfo=self.tz))]

    def test_fail_init_end_time_before_start_time(self):
        with self.assertRaises(ValueError):
            scheduler.FlexSlotFinder(datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                     datetime(2025, 8, 5, 12, 30, tzinfo=self.tz),
                                     30)

        with self.assertRaises(ValueError):
            scheduler.FlexSlotFinder(datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                     datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                     0)

    def test_no_valid_slot_found(self):
        flex_slot_finder = scheduler.FlexSlotFinder(datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                                    datetime(2025, 8, 5, 14, 30, tzinfo=self.tz),
                                                    30)

        start_dt, end_dt = flex_slot_finder.find_valid_slot(self.events_clash)
        self.assertEqual(start_dt, datetime(2025, 8, 5, 12, 0, tzinfo=self.tz))
        self.assertEqual(end_dt, datetime(2025, 8, 5, 12, 30, tzinfo=self.tz))
        self.assertEqual(flex_slot_finder.no_clashes, False)

    def test_valid_slot_found(self):
        flex_slot_finder = scheduler.FlexSlotFinder(datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                                    datetime(2025, 8, 5, 20, 30, tzinfo=self.tz),
                                                    30)

        start_dt, end_dt = flex_slot_finder.find_valid_slot(self.events_clash)

        self.assertEqual(start_dt, datetime(2025, 8, 5, 20, 0, tzinfo=self.tz))
        self.assertEqual(end_dt, datetime(2025, 8, 5, 20, 30, tzinfo=self.tz))
        self.assertEqual(flex_slot_finder.no_clashes, True)

class TestTimezone(unittest.TestCase):
    def test_singleton_behavior(self):
        tz1 = scheduler.Timezone()
        tz2 = scheduler.Timezone()
        self.assertIs(tz1, tz2)

    def test_timezone_is_localzone_name(self):
        tz = scheduler.Timezone()
        self.assertEqual(tz.timezone, get_localzone_name())

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo(get_localzone_name())
        scheduler.Database.clear_instances()
        self.db = scheduler.Database("test_scheduler.db")

    def test_singleton_behavior(self):
        db1 = scheduler.Database("test_scheduler.db")
        db2 = scheduler.Database("test_scheduler.db")
        self.assertIs(db1, db2)

    def test_events_table_created(self):
        # Connect to the test database
        import sqlite3
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        # Query for the events table schema
        cursor.execute("PRAGMA table_info(events);")
        columns = [col[1] for col in cursor.fetchall()]
        expected_columns = [
            "id", "summary", "is_flexible", "event_start_dt", "event_end_dt",
            "duration", "valid_start_dt", "valid_end_dt", "timezone",
            "google_id", "last_updated"
        ]
        self.assertEqual(columns, expected_columns)
        conn.close()

    def test_event_status(self):
        event = RandomEventBuilder().generate_fixed_event()

        # Event is not in DB yet, should be NEW
        status = self.db.event_status(event)
        self.assertEqual(status, scheduler.EventStatus.NEW)

        # Add event to DB
        self.db.add_event(event)

        # Event is now in DB and unchanged, should be UNCHANGED
        status = self.db.event_status(event)
        self.assertEqual(status, scheduler.EventStatus.UNCHANGED)

        # Modify event summary
        event.summary = event.summary + "_modified"
        status = self.db.event_status(event)
        self.assertEqual(status, scheduler.EventStatus.MODIFIED)

    def test_add_event_successful(self):
        event = RandomEventBuilder().generate_fixed_event()
        self.db.add_event(event)

        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE google_id = ?", (event.google_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], event.summary)
        self.assertEqual(row[2], event.is_flexible)
        self.assertEqual(row[3], event.start_dt.isoformat())
        self.assertEqual(row[4], event.end_dt.isoformat())
        self.assertEqual(row[5], event.duration)
        self.assertEqual(row[6], event.valid_start_dt.isoformat())
        self.assertEqual(row[7], event.valid_end_dt.isoformat())
        self.assertEqual(row[8], get_localzone_name())
        self.assertEqual(row[9], event.google_id)
        conn.close()

    def test_add_event_fails_duplicate_event(self):
        event = RandomEventBuilder().generate_fixed_event()
        self.db.add_event(event)
        with self.assertRaises(ValueError):
            self.db.add_event(event)

    def test_del_event_successful(self):
        event = RandomEventBuilder().generate_fixed_event()
        self.db.add_event(event)
        self.db.del_event(event)

        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE google_id = ?", (event.google_id,))
        row = cursor.fetchone()
        self.assertIsNone(row)
        conn.close()

    def test_del_event_fails_event_not_found(self):
        event = RandomEventBuilder().generate_fixed_event()
        with self.assertRaises(ValueError):
            self.db.del_event(event)

    def test_edit_event_updates_event(self):
        # Create and add a fixed event
        event = RandomEventBuilder().generate_fixed_event()
        self.db.add_event(event)

        # Modify event fields
        new_summary = event.summary + "_edited"
        new_start_dt = event.start_dt + timedelta(hours=1)
        new_end_dt = event.end_dt + timedelta(hours=1)
        event.summary = new_summary
        event.start_dt = new_start_dt
        event.end_dt = new_end_dt
        event.valid_start_dt = new_start_dt
        event.valid_end_dt = new_end_dt

        # Edit the event in the database
        self.db.edit_event(event)

        # Fetch the event from the database and check updated fields
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT summary, event_start_dt, event_end_dt FROM events WHERE google_id = ?",
                       (event.google_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], new_summary)
        self.assertEqual(row[1], new_start_dt.isoformat())
        self.assertEqual(row[2], new_end_dt.isoformat())

    def test_edit_event_fails_event_not_found(self):
        event = RandomEventBuilder().generate_fixed_event()
        with self.assertRaises(ValueError):
            self.db.edit_event(event)

    def test_edit_event_fails_no_changes(self):
        event = RandomEventBuilder().generate_fixed_event()
        self.db.add_event(event)
        with self.assertRaises(ValueError):
            self.db.edit_event(event)

    def test_get_events_fails_invalid_date_range(self):
        from_dt = datetime(2025, 8, 5, 12, 0, tzinfo=self.tz)
        to_dt = datetime(2025, 8, 5, 11, 0, tzinfo=self.tz)
        with self.assertRaises(ValueError):
            self.db.get_events_in_date_range(from_dt, to_dt, scheduler.EventType.ALL)

    def test_get_events_returns_correct_events(self):
        # Create two fixed and one flexible event
        builder = RandomEventBuilder()
        fixed_event1 = builder.generate_fixed_event()
        fixed_event2 = builder.generate_fixed_event()
        flex_event = builder.generate_flexible_event()

        # Add events to the database
        self.db.add_event(fixed_event1)
        self.db.add_event(fixed_event2)
        self.db.add_event(flex_event)

        # Define a range that includes all events
        from_dt = min(fixed_event1.start_dt, fixed_event2.start_dt, flex_event.start_dt)
        to_dt = max(fixed_event1.end_dt, fixed_event2.end_dt, flex_event.end_dt)

        print(f"From: {from_dt}, To: {to_dt}")

        # Get all events
        all_events = self.db.get_events_in_date_range(from_dt, to_dt, scheduler.EventType.ALL)
        self.assertEqual(len(all_events), 3)
        # Get only fixed events
        fixed_events = self.db.get_events_in_date_range(from_dt, to_dt, event_type=scheduler.EventType.FIXED)
        print(fixed_events)
        self.assertTrue(all(isinstance(e, scheduler.FixedEvent) for e in fixed_events))
        self.assertEqual(len(fixed_events), 2)

        # Get only flexible events
        flex_events = self.db.get_events_in_date_range(from_dt, to_dt, scheduler.EventType.FLEXIBLE)
        print(flex_events)
        self.assertTrue(all(isinstance(e, scheduler.FlexibleEvent) for e in flex_events))
        self.assertEqual(len(flex_events), 1)


    def test_get_events_order_by(self):
        # Create events with specific start times
        event1 = scheduler.FixedEvent("Event 1",
                                      datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                      datetime(2025, 8, 5, 18, 0, tzinfo=self.tz))
        event2 = scheduler.FixedEvent("Event 2",
                                      datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                      datetime(2025, 8, 5, 13, 0, tzinfo=self.tz))
        event3 = scheduler.FixedEvent("Event 3",
                                      datetime(2025, 8, 5, 16, 0, tzinfo=self.tz),
                                      datetime(2025, 8, 5, 17, 0, tzinfo=self.tz))

        # Add events to the database
        self.db.add_event(event1)
        self.db.add_event(event2)
        self.db.add_event(event3)

        from_dt = datetime(2025, 8, 5, 0, 0, tzinfo=self.tz)
        to_dt = datetime(2025, 8, 6, 0, 0, tzinfo=self.tz)

        events = self.db.get_events_in_date_range(from_dt, to_dt, scheduler.EventType.ALL)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].summary, "Event 2")
        self.assertEqual(events[1].summary, "Event 1")
        self.assertEqual(events[2].summary, "Event 3")

        # Check order by End date
        events_desc = self.db.get_events_in_date_range(from_dt, to_dt, scheduler.EventType.ALL, order_by=scheduler.OrderBy.END)
        self.assertEqual(len(events_desc), 3)
        self.assertEqual(events_desc[0].summary, "Event 2")
        self.assertEqual(events_desc[1].summary, "Event 3")
        self.assertEqual(events_desc[2].summary, "Event 1")

    def test_update_timestamp_successful(self):
        event = RandomEventBuilder().generate_fixed_event()
        self.db.add_event(event)

        # Capture the original timestamp
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT last_updated FROM events WHERE google_id = ?", (event.google_id,))
        original_timestamp = cursor.fetchone()[0]
        conn.close()

        event.summary = event.summary + "_updated"
        # Update the timestamp
        self.db.edit_event(event)

        # Fetch the updated timestamp
        conn = sqlite3.connect(self.db.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT last_updated FROM events WHERE google_id = ?", (event.google_id,))
        updated_timestamp = cursor.fetchone()[0]
        conn.close()

        self.assertNotEqual(original_timestamp, updated_timestamp)

    def tearDown(self):
        if os.path.exists("test_scheduler.db"):
            os.remove("test_scheduler.db")

        scheduler.Database.clear_instances()

class TestGoogleCalendar(unittest.TestCase):

    def test_singleton_behavior(self):
        gc1 = scheduler.GoogleCalendar()
        gc2 = scheduler.GoogleCalendar()
        self.assertIs(gc1, gc2)

    @patch("scheduler.build")
    @patch("scheduler.Credentials")
    def test_add_event_successfully(self, mock_creds, mock_build):
        # Mock the service and its methods
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {"id": "fake_id", "htmlLink": "http://fake"}
        mock_events.insert.return_value = mock_insert
        mock_service.events.return_value = mock_events
        mock_build.return_value = mock_service

        # Create a fake event
        event = RandomEventBuilder().generate_fixed_event()

        # Patch authentication to avoid file I/O
        with patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__authenticate", return_value=MagicMock()):
            gc = scheduler.GoogleCalendar()
            event_id = gc.add_event(event)
            self.assertEqual(event_id, "fake_id")


    @patch("scheduler.build")
    @patch("scheduler.Credentials")
    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_add_event_handles_http_error(self, mock_exit, mock_creds, mock_build):
        # Mock the service to raise HttpError on insert().execute()
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.side_effect = HttpError(resp=MagicMock(), content=b"error")
        mock_events.insert.return_value = mock_insert
        mock_service.events.return_value = mock_events
        mock_build.return_value = mock_service

        event = RandomEventBuilder().generate_fixed_event()
        with patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__authenticate", return_value=MagicMock()):
            gc = scheduler.GoogleCalendar()
            with self.assertRaises(SystemExit):
                gc.add_event(event)
            mock_exit.assert_called_with(1)


    @patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__get_events_json")
    @patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__to_event_object")
    def test_get_events_returns_current_and_deleted(self, mock_to_event, mock_get_json):
        # Prepare mock data
        start_dt = datetime(2025, 8, 5, 0, 0)
        end_dt = datetime(2025, 8, 6, 0, 0)
        event_json_current = {'status': 'confirmed', 'summary': 'Event1', 'start': {'dateTime': '2025-08-05T10:00:00'},
                              'end': {'dateTime': '2025-08-05T11:00:00'}, 'id': 'id1'}
        event_json_deleted = {'status': 'cancelled', 'summary': 'Event2', 'start': {'dateTime': '2025-08-05T12:00:00'},
                              'end': {'dateTime': '2025-08-05T13:00:00'}, 'id': 'id2'}
        mock_get_json.return_value = [event_json_current, event_json_deleted]
        mock_to_event.side_effect = ['event_obj_current', 'event_obj_deleted']

        with patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__authenticate", return_value=MagicMock()):
            gc = scheduler.GoogleCalendar()
            current, deleted = gc.get_events(start_dt, end_dt)

        self.assertEqual(current, ['event_obj_current'])
        self.assertEqual(deleted, ['event_obj_deleted'])
        mock_get_json.assert_called_once_with(start_dt, end_dt, get_deleted=True)
        self.assertEqual(mock_to_event.call_count, 2)

    def test_get_events_raises_value_error_for_invalid_range(self):
        start_dt = datetime(2025, 8, 6, 4, 0)
        end_dt = datetime(2025, 8, 6, 3, 0)
        with patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__authenticate", return_value=MagicMock()):
            gc = scheduler.GoogleCalendar()
            with self.assertRaises(ValueError) as cm:
                gc.get_events(start_dt, end_dt)
            self.assertEqual(str(cm.exception), "Start date/time must be before end date/time")


    def test_edit_event_fails_event_not_found(self):
        event = RandomEventBuilder().generate_fixed_event()
        with patch.object(scheduler.GoogleCalendar, "_GoogleCalendar__authenticate", return_value=MagicMock()):
            gc = scheduler.GoogleCalendar()
            with self.assertRaises(ValueError):
                gc.edit_event(event)

class TestEventManager(unittest.TestCase):
    def setUp(self):
        self.tz = zoneinfo.ZoneInfo(get_localzone_name())

        self.cur_events = [scheduler.FixedEvent("Event 1",
                                                datetime(2025, 8, 5, 12, 0, tzinfo=self.tz),
                                                datetime(2025, 8, 5, 13, 0, tzinfo=self.tz)),
                           scheduler.FixedEvent("Event 2",
                                                datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                                datetime(2025, 8, 5, 20, 0, tzinfo=self.tz))]

        self.del_events = [scheduler.FixedEvent("Del Event 1",
                                                datetime(2025, 8, 5, 13, 0, tzinfo=self.tz),
                                                datetime(2025, 8, 5, 14, 0, tzinfo=self.tz)),
                           scheduler.FixedEvent("Del Event 2",
                                                datetime(2025, 8, 5, 15, 0, tzinfo=self.tz),
                                                datetime(2025, 8, 5, 16, 0, tzinfo=self.tz))]

    @patch("scheduler.GoogleCalendar.get_events")
    def test_sync_fails_no_events_in_current_or_deleted_lists(self, mock_gc_events):
        mock_gc_events.return_value = ([], [])
        start_dt = datetime(2025, 8, 5, 0, 0, tzinfo=self.tz)
        end_dt = datetime(2025, 8, 6, 1, 0, tzinfo=self.tz)
        em = scheduler.EventManager()
        with self.assertRaises(ValueError):
            em.sync_gc_to_db(start_dt, end_dt)

    @patch("scheduler.Database.add_event")
    @patch("scheduler.Database.event_status")
    @patch("scheduler.GoogleCalendar.get_events")
    def test_sync_gc_to_db_handles_new_events(self, mock_gc_events, mock_event_status, mock_add_event):
        # Create a mock event
        mock_gc_events.return_value = (self.cur_events, [])
        mock_event_status.return_value = scheduler.EventStatus.NEW

        # Call the method
        scheduler.EventManager.sync_gc_to_db(datetime(2025, 8, 5, 0, 0), datetime(2025, 8, 6, 0, 0))

        # Assert add_event was called with the new event
        assert mock_add_event.call_count == len(self.cur_events)

    @patch("scheduler.Database.edit_event")
    @patch("scheduler.Database.event_status")
    @patch("scheduler.GoogleCalendar.get_events")
    def test_sync_gc_to_db_handles_modified_events(self, mock_gc_events, mock_event_status, mock_edit_event):
        # Create a mock event
        mock_gc_events.return_value = (self.cur_events, [])
        mock_event_status.return_value = scheduler.EventStatus.MODIFIED

        # Call the method
        scheduler.EventManager.sync_gc_to_db(datetime(2025, 8, 5, 0, 0), datetime(2025, 8, 6, 0, 0))

        # Assert add_event was called with the new event
        assert mock_edit_event.call_count == len(self.cur_events)

    @patch("scheduler.Database.del_event")
    @patch("scheduler.GoogleCalendar.get_events")
    def test_sync_gc_to_db_handles_deleted_events(self, mock_gc_events, mock_del_event):
        # Create a mock event
        mock_gc_events.return_value = ([], self.del_events)

        # Call the method
        scheduler.EventManager.sync_gc_to_db(datetime(2025, 8, 5, 0, 0), datetime(2025, 8, 6, 0, 0))

        # Assert add_event was called with the new event
        assert mock_del_event.call_count == len(self.cur_events)



class TestDateTimeConverter(unittest.TestCase):
    def setUp(self):
        self.dtc = scheduler.DateTimeConverter()

    def test_convert_str_to_time_successful(self):
        time_str = "14:30"
        expected_time = datetime(2025, 8, 5, 14, 30).time()
        result = self.dtc.convert_str_to_time(time_str)
        self.assertEqual(result, expected_time)

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_convert_str_to_time_fails_wrong_time_format(self, mock_exit):
        invalid_time_formats = ["12-00",
                                "12:00:01",
                                "12.00",
                                "abc",
                                "",
                                "28:00",
                                "12:76"]

        for time_str in invalid_time_formats:
            with self.assertRaises(SystemExit):
                self.dtc.convert_str_to_time(time_str)

        self.assertEqual(mock_exit.call_count, len(invalid_time_formats))
        mock_exit.assert_called_with(1)

    def test_convert_str_to_date_successful(self):
        date_str = "05-08-2025"
        expected_date = datetime(2025, 8, 5, 14, 30).date()
        result = self.dtc.convert_str_to_date(date_str)
        self.assertEqual(result, expected_date)

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_convert_str_to_date_fails_wrong_date_format(self, mock_exit):
        invalid_date_formats = ["05.08.2025",
                                "05/08/2025",
                                "2025-05-08",
                                "cat",
                                "12345",
                                "65-08-2025",
                                "12-70-2025",
                                "05-08-25"]

        for date_str in invalid_date_formats:
            with self.assertRaises(SystemExit):
                self.dtc.convert_str_to_date(date_str)

        self.assertEqual(mock_exit.call_count, len(invalid_date_formats))
        mock_exit.assert_called_with(1)

    def test_convert_str_to_dt_successful(self):
        date_str = "05-08-2025"
        expected_dt = datetime(2025, 8, 5)
        result = self.dtc.convert_str_to_dt(date_str)
        self.assertEqual(result, expected_dt)

    @patch("scheduler.sys.exit", side_effect=SystemExit)
    def test_convert_str_to_dt_fails_wrong_date_format(self, mock_exit):
        invalid_date_formats = ["05.08.2025",
                                "05/08/2025",
                                "2025-05-08",
                                "cat",
                                "12345",
                                "65-08-2025",
                                "12-70-2025",
                                "05-08-25"]

        for date_str in invalid_date_formats:
            with self.assertRaises(SystemExit):
                self.dtc.convert_str_to_dt(date_str)

        self.assertEqual(mock_exit.call_count, len(invalid_date_formats))
        mock_exit.assert_called_with(1)

    def test_get_cur_midnight_successful(self):
        tz = zoneinfo.ZoneInfo(get_localzone_name())
        now = datetime.now(tz)
        expected_midnight = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)
        result = self.dtc.get_cur_midnight(now)
        self.assertEqual(result, expected_midnight)

    def test_get_next_midnight_successful(self):
        tz = zoneinfo.ZoneInfo(get_localzone_name())
        now = datetime.now(tz)
        expected_midnight = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz) + timedelta(days=1)
        result = self.dtc.get_next_midnight(now)
        self.assertEqual(result, expected_midnight)

if __name__ == '__main__':
    unittest.main()
