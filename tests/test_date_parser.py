import unittest
from datetime import datetime

from app.services.date_parser import build_event_time, parse_datetime


class DateParserTests(unittest.TestCase):
    def test_parses_explicit_dmy_date_with_time(self):
        parsed = parse_datetime("16.08.2026 o 12:00")
        self.assertEqual(parsed, datetime(2026, 8, 16, 12, 0))

    def test_parses_iso_date_with_time(self):
        parsed = parse_datetime("2026-08-16 o 12:00")
        self.assertEqual(parsed, datetime(2026, 8, 16, 12, 0))

    def test_build_event_time_keeps_requested_duration(self):
        start, end = build_event_time("16.08.2026 o 12:00", 90)
        self.assertEqual(start, datetime(2026, 8, 16, 12, 0))
        self.assertEqual(end, datetime(2026, 8, 16, 13, 30))

    def test_invalid_explicit_date_is_reported_as_value_error(self):
        with self.assertRaises(ValueError):
            parse_datetime("2026-13-40 o 12:00")

    def test_missing_day_still_fails(self):
        with self.assertRaisesRegex(ValueError, "Brakuje dnia wydarzenia"):
            parse_datetime("o 12:00")


if __name__ == "__main__":
    unittest.main()
