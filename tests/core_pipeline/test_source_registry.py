import unittest

from src.core_pipeline.source_registry import (
    AUXILIARY_DAILYHOT_ROUTES,
    DAILYHOT_ROUTE_GROUPS,
    FAILED_DEFAULT_ROUTES,
    PRIMARY_HOT_ROUTES,
    REQUIRED_DETAIL_PLATFORMS,
    route_role,
)


class SourceRegistryTests(unittest.TestCase):
    def test_required_detail_platforms_are_fixed(self):
        self.assertEqual(REQUIRED_DETAIL_PLATFORMS, ("weibo", "xiaohongshu", "baidu"))

    def test_primary_hot_routes_prioritize_required_platforms(self):
        self.assertEqual(PRIMARY_HOT_ROUTES[:3], ("weibo", "xiaohongshu", "baidu"))

    def test_dailyhot_route_groups_include_domestic_and_foreign_context(self):
        self.assertIn("weibo", DAILYHOT_ROUTE_GROUPS["core_discovery"])
        self.assertIn("baidu", DAILYHOT_ROUTE_GROUPS["core_discovery"])
        self.assertIn("xiaohongshu", DAILYHOT_ROUTE_GROUPS["core_discovery"])
        self.assertIn("github", DAILYHOT_ROUTE_GROUPS["foreign_tech"])
        self.assertIn("hellogithub", DAILYHOT_ROUTE_GROUPS["foreign_tech"])

    def test_failed_default_routes_are_not_main_chain(self):
        self.assertIn("hackernews", FAILED_DEFAULT_ROUTES)
        self.assertIn("producthunt", FAILED_DEFAULT_ROUTES)
        self.assertNotIn("hackernews", AUXILIARY_DAILYHOT_ROUTES)

    def test_route_role_returns_auxiliary_for_news(self):
        self.assertEqual(route_role("sina-news"), "auxiliary_news")
        self.assertEqual(route_role("unknown-route"), "unknown")


if __name__ == "__main__":
    unittest.main()
