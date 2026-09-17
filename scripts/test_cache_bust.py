#!/usr/bin/env python3
"""RED tests for GitHub Camo cache-bust query on activity card URLs."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cards import bust_activity_urls  # noqa: E402

SAMPLE = """
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/activity-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/activity-light.svg">
  <img src="https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/activity-dark.svg" width="100%" alt="x">
</picture>
"""


class BustActivityUrlsTests(unittest.TestCase):
    def test_appends_version_query(self):
        out = bust_activity_urls(SAMPLE, "20260826")
        self.assertEqual(out.count("activity-dark.svg?v=20260826"), 2)
        self.assertEqual(out.count("activity-light.svg?v=20260826"), 1)

    def test_replaces_existing_version_query(self):
        src = SAMPLE.replace(".svg", ".svg?v=old")
        out = bust_activity_urls(src, "new")
        self.assertNotIn("v=old", out)
        self.assertEqual(out.count("?v=new"), 3)

    def test_leaves_other_assets_alone(self):
        src = "https://cdn.jsdelivr.net/gh/Borisserz/Borisserz@main/assets/hero-dark.svg"
        self.assertEqual(bust_activity_urls(src, "1"), src)


if __name__ == "__main__":
    unittest.main()
