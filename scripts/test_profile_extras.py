#!/usr/bin/env python3
"""Tests for recent-activity, weekday habits and isometric levels."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cards import (  # noqa: E402
    APPS,
    app_readme_block,
    apply_fetched_title,
    contrib_level,
    patch_markers,
    summarize_event,
    weekday_counts,
)


class SummarizeEventTests(unittest.TestCase):
    def test_merged_pull_request(self):
        event = {
            "type": "PullRequestEvent",
            "repo": {"name": "OneBusAway/onebusaway-ios"},
            "payload": {
                "action": "closed",
                "pull_request": {
                    "merged": True,
                    "number": 1294,
                    "html_url": "https://github.com/OneBusAway/onebusaway-ios/pull/1294",
                    "title": "Fix map",
                },
            },
        }
        row = summarize_event(event)
        self.assertEqual(row["verb"], "merged")
        self.assertEqual(row["repo"], "OneBusAway/onebusaway-ios")
        self.assertIn("1294", row["label"])
        self.assertTrue(row["href"].endswith("/pull/1294"))

    def test_skips_noise_watch_events(self):
        event = {"type": "WatchEvent", "repo": {"name": "foo/bar"}, "payload": {}}
        self.assertIsNone(summarize_event(event))

    def test_opened_issue(self):
        event = {
            "type": "IssuesEvent",
            "repo": {"name": "Borisserz/FoodTracker"},
            "payload": {
                "action": "opened",
                "issue": {
                    "number": 3,
                    "html_url": "https://github.com/Borisserz/FoodTracker/issues/3",
                    "title": "Crash on launch",
                },
            },
        }
        row = summarize_event(event)
        self.assertEqual(row["verb"], "opened")
        self.assertIn("#3", row["label"])

    def test_fills_title_when_events_api_omits_it(self):
        row = {
            "verb": "opened",
            "repo": "foo/bar",
            "href": "https://github.com/foo/bar/pull/1",
            "label": "foo/bar #1",
            "detail": "",
        }
        out = apply_fetched_title(row, {"title": "Fix the map overlay"})
        self.assertEqual(out["detail"], "Fix the map overlay")

    def test_keeps_existing_title(self):
        row = {"detail": "Already here"}
        out = apply_fetched_title(row, {"title": "Other"})
        self.assertEqual(out["detail"], "Already here")


class WeekdayCountsTests(unittest.TestCase):
    def test_sums_each_weekday(self):
        weeks = [{
            "contributionDays": [
                {"date": "2026-07-12", "contributionCount": 1},  # Sunday
                {"date": "2026-07-13", "contributionCount": 2},
                {"date": "2026-07-14", "contributionCount": 0},
                {"date": "2026-07-15", "contributionCount": 4},
                {"date": "2026-07-16", "contributionCount": 0},
                {"date": "2026-07-17", "contributionCount": 0},
                {"date": "2026-07-18", "contributionCount": 8},
            ]
        }]
        counts = weekday_counts(weeks)
        self.assertEqual(counts, [1, 2, 0, 4, 0, 0, 8])


class ContribLevelTests(unittest.TestCase):
    def test_zero_is_empty(self):
        self.assertEqual(contrib_level(0, 40), 0)

    def test_max_is_top_level(self):
        self.assertEqual(contrib_level(40, 40), 4)

    def test_mid_is_between(self):
        self.assertIn(contrib_level(10, 40), (1, 2, 3))


class PatchMarkersTests(unittest.TestCase):
    def test_replaces_inner_block(self):
        src = "before\n<!-- feed:start -->\nold\n<!-- feed:end -->\nafter\n"
        out = patch_markers(src, "<!-- feed:start -->", "<!-- feed:end -->", "new")
        self.assertIn("<!-- feed:start -->\nnew\n<!-- feed:end -->", out)
        self.assertTrue(out.startswith("before"))
        self.assertIn("after", out)


class AppReadmeBlockTests(unittest.TestCase):
    def test_omits_screenshots_even_when_jpgs_exist(self):
        tmp = tempfile.mkdtemp()
        for app in APPS:
            with open(os.path.join(tmp, "app-%s.jpg" % app["slug"]), "w") as fh:
                fh.write("x")
        block = app_readme_block(tmp)
        self.assertNotIn(".jpg", block)
        self.assertIn("app-workouttracker", block)


if __name__ == "__main__":
    unittest.main()
