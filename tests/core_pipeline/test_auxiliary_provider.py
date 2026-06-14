import unittest

from src.core_pipeline.providers.auxiliary import evidence_from_dailyhot_record
from src.core_pipeline.types import HotRecord


class AuxiliaryProviderTests(unittest.TestCase):
    def test_dailyhot_desc_becomes_auxiliary_evidence(self):
        record = HotRecord(
            id="hot_github_001",
            source="dailyhotapi",
            platform="github",
            route="github",
            category="foreign_tech",
            title="项目趋势",
            rank=1,
            hot_value="100",
            url="https://github.com/example/repo",
            mobile_url="",
            desc="GitHub 趋势项目描述",
            author="example",
            cover="",
            timestamp="",
            captured_at="2026-06-14T20:00:00+08:00",
            raw_payload={"repo": "repo"},
            fetch_status="ok",
            error_type=None,
        )

        evidence = evidence_from_dailyhot_record(record, "2026-06-14T20:10:00+08:00")

        self.assertEqual(evidence.source_role, "auxiliary")
        self.assertEqual(evidence.platform, "github")
        self.assertIn("GitHub 趋势项目描述", evidence.content)


if __name__ == "__main__":
    unittest.main()