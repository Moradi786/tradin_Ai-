import unittest

import core


class DominanceAlignmentTests(unittest.TestCase):
    def test_total_is_a_separate_market_alignment_check(self):
        previous = {
            "BTC.D": 52.0, "USDT.D": 6.0, "OTHERS.D": 8.0,
            "TOTAL": 2_000_000_000_000,
            "TOTAL2": 960_000_000_000,
            "TOTAL3": 500_000_000_000,
        }
        current = {
            "BTC.D": 51.0, "USDT.D": 5.8, "OTHERS.D": 8.2,
            "TOTAL": 2_050_000_000_000,
            "TOTAL2": 1_004_000_000_000,
            "TOTAL3": 520_000_000_000,
        }

        result = core.market_alignment(current, previous)

        self.assertEqual(result["total"], 6)
        self.assertTrue(result["long_details"]["TOTAL"])
        self.assertEqual(result["long"], 6)
        self.assertEqual(result["short"], 0)

    def test_missing_snapshot_reports_six_checks_without_claiming_alignment(self):
        result = core.market_alignment(None, None)

        self.assertEqual(result["total"], 6)
        self.assertEqual(result["long"], 0)
        self.assertEqual(result["short"], 0)
        self.assertFalse(any(result["long_details"].values()))


if __name__ == "__main__":
    unittest.main()
