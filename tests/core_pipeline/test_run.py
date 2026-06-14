import unittest

from src.core_pipeline.run import output_paths


class RunTests(unittest.TestCase):
    def test_output_paths_are_fixed(self):
        paths = output_paths()

        self.assertEqual(str(paths["hot_records"]), "data/raw/dailyhot_records.json")
        self.assertEqual(str(paths["detail_evidence"]), "data/evidence/detail_evidence.json")
        self.assertEqual(str(paths["topic_briefs"]), "data/processed/topic_briefs.json")
        self.assertEqual(str(paths["markdown_report"]), "reports/core_platform_topic_digest.md")


if __name__ == "__main__":
    unittest.main()