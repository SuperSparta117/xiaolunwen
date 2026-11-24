import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from er.io import read_csv_sample, read_sql_sample
from er.config import A_CANDIDATE_PATH, A_QUERY_PATH


class TestBoundedReaders(unittest.TestCase):
    def test_sql_reader_is_bounded(self):
        rows = read_sql_sample(A_QUERY_PATH, 12)
        self.assertEqual(len(rows), 12)
        self.assertTrue(rows[0]["village_name"])

    def test_csv_reader_is_bounded(self):
        rows = read_csv_sample(A_CANDIDATE_PATH, 12)
        self.assertEqual(len(rows), 12)
        self.assertIn("小区名", rows[0])


if __name__ == "__main__":
    unittest.main()
