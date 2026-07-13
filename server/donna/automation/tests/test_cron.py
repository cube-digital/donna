"""Plan 13 §7.1 — cron parser + next-fire tests."""
from __future__ import annotations

from datetime import datetime, timezone as _tz

from django.test import SimpleTestCase

from donna.automation.cron import next_fire_after, parse


class ParseCronTests(SimpleTestCase):
    def test_wildcards_expand_to_full_range(self):
        out = parse("* * * * *")
        self.assertEqual(out["minute"], set(range(60)))
        self.assertEqual(out["hour"], set(range(24)))

    def test_step_values(self):
        out = parse("*/15 * * * *")
        self.assertEqual(out["minute"], {0, 15, 30, 45})

    def test_lists_and_ranges(self):
        out = parse("0 9,17 1-5 * *")
        self.assertEqual(out["minute"], {0})
        self.assertEqual(out["hour"], {9, 17})
        self.assertEqual(out["dom"], {1, 2, 3, 4, 5})

    def test_wrong_field_count_raises(self):
        with self.assertRaises(ValueError):
            parse("* * * *")


class NextFireAfterTests(SimpleTestCase):
    def test_every_minute_advances_one_minute(self):
        cursor = datetime(2026, 6, 26, 9, 0, 30, tzinfo=_tz.utc)
        out = next_fire_after("* * * * *", cursor)
        self.assertEqual(out, datetime(2026, 6, 26, 9, 1, tzinfo=_tz.utc))

    def test_hourly_fires_on_the_zero(self):
        cursor = datetime(2026, 6, 26, 9, 17, tzinfo=_tz.utc)
        out = next_fire_after("0 * * * *", cursor)
        self.assertEqual(out, datetime(2026, 6, 26, 10, 0, tzinfo=_tz.utc))

    def test_specific_time_rolls_to_next_day(self):
        cursor = datetime(2026, 6, 26, 22, 0, tzinfo=_tz.utc)
        out = next_fire_after("0 9 * * *", cursor)
        self.assertEqual(out, datetime(2026, 6, 27, 9, 0, tzinfo=_tz.utc))

    def test_dom_filter_skips_days(self):
        cursor = datetime(2026, 6, 26, 22, 0, tzinfo=_tz.utc)
        out = next_fire_after("0 9 1 * *", cursor)
        self.assertEqual(out, datetime(2026, 7, 1, 9, 0, tzinfo=_tz.utc))

    def test_dow_monday_only(self):
        # 2026-06-26 is a Friday. Next Monday at 09:00 = 2026-06-29.
        cursor = datetime(2026, 6, 26, 22, 0, tzinfo=_tz.utc)
        out = next_fire_after("0 9 * * 1", cursor)
        self.assertEqual(out.weekday(), 0)
        self.assertEqual(out, datetime(2026, 6, 29, 9, 0, tzinfo=_tz.utc))
