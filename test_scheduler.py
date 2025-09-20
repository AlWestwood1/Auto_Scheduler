import string
import unittest
from unittest.mock import patch
import random
from tzlocal import get_localzone_name

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
            flex_slot_finder = scheduler.FlexSlotFinder(datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
                                                        datetime(2025, 8, 5, 12, 30, tzinfo=self.tz),
                                                        30)

        with self.assertRaises(ValueError):
            flex_slot_finder = scheduler.FlexSlotFinder(datetime(2025, 8, 5, 14, 0, tzinfo=self.tz),
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

if __name__ == '__main__':
    unittest.main()
