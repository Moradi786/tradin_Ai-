import unittest

from signal_quality import market_direction_confirmed


class MarketDirectionConfirmedTests(unittest.TestCase):
    def test_long_requires_score_and_alignment(self):
        self.assertTrue(market_direction_confirmed(
            {"score": 70, "long": 3}, "LONG", True, 65, 35, 3
        ))

    def test_long_rejects_good_score_without_alignment(self):
        self.assertFalse(market_direction_confirmed(
            {"score": 80, "long": 2}, "LONG", True, 65, 35, 3
        ))

    def test_short_requires_score_and_alignment(self):
        self.assertTrue(market_direction_confirmed(
            {"score": 30, "short": 4}, "SHORT", True, 65, 35, 3
        ))

    def test_short_rejects_score_outside_threshold(self):
        self.assertFalse(market_direction_confirmed(
            {"score": 40, "short": 5}, "SHORT", True, 65, 35, 3
        ))

    def test_legacy_fallback_when_score_missing(self):
        market = {"score": None, "long": 3, "short": 2}
        self.assertTrue(market_direction_confirmed(
            market, "LONG", True, 65, 35, 3
        ))
        self.assertFalse(market_direction_confirmed(
            market, "SHORT", True, 65, 35, 3
        ))

    def test_unknown_direction_is_rejected(self):
        self.assertFalse(market_direction_confirmed(
            {"score": 100, "long": 5}, "WAIT", True, 65, 35, 3
        ))


if __name__ == "__main__":
    unittest.main()
