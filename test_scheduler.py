import unittest
from unittest.mock import patch
import scheduler
from datetime import datetime
import zoneinfo


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

    def test_generate_dts_fail_end_dt_before_start_dt(self):
        date_str = "05-08-2025"
        with self.assertRaises(ValueError):
            self.eb._generate_dts(date_str, "12:00", "11:00")
            self.eb._generate_dts(date_str, "23:59", "00:00")

    def test_generate_dts_success(self):
        date_str = "05-08-2025"
        tz = zoneinfo.ZoneInfo("Europe/London")
        with patch("scheduler.Timezone.local_tz") as mock_tz:
            mock_tz.return_value = tz
            self.assertEqual(self.eb._generate_dts(date_str, "12:00", "13:00"),
                             (datetime(2025, 8, 5, 12, 0, tzinfo=tz), datetime(2025, 8, 5, 13, 0, tzinfo=tz)))

class TestFixedEventBuilder(unittest.TestCase):
    def setUp(self):
        pass


if __name__ == '__main__':
    unittest.main()
