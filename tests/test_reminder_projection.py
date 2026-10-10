#!/usr/bin/env python3
import unittest

from cal_system.reminder_checker import project_current_occurrence


class ReminderProjectionTests(unittest.TestCase):
    def test_timed_due_date_is_projected(self):
        item = {"id": "rem_1", "due_date": "10.10.2026 21:04", "channel_id": "123"}
        projected = project_current_occurrence(item)
        self.assertIsNotNone(projected)
        self.assertEqual(projected["id"], "rem_1")

    def test_date_only_due_date_still_projected(self):
        item = {"id": "rem_2", "due_date": "10.10.2026"}
        self.assertIsNotNone(project_current_occurrence(item))


if __name__ == "__main__":
    unittest.main()
