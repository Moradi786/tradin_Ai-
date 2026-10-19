import unittest
from advanced_engine import score_setup, risk_plan, evaluate_forward_path


class AdvancedEngineTests(unittest.TestCase):
    def test_strong_long_setup_eligible(self):
        result = score_setup("LONG", volume_ratio=1.5, price_move_pct=0.2,
            buy_ratio=0.62, oi_change_pct=0.8, netflow=40,
            trend_1h="UP", trend_4h="UP", distance_to_level_pct=0.5)
        self.assertTrue(result["eligible"])
        self.assertGreaterEqual(result["score"], 75)

    def test_rejects_late_move_and_wrong_trend(self):
        result = score_setup("LONG", volume_ratio=3.5, price_move_pct=2.0,
            buy_ratio=0.62, oi_change_pct=0.8, netflow=40,
            trend_1h="DOWN", trend_4h="UP", distance_to_level_pct=0.5)
        self.assertFalse(result["eligible"])

    def test_short_risk_plan(self):
        plan = risk_plan(100, 2, "SHORT")
        self.assertAlmostEqual(plan["stop_reference"], 103)
        self.assertAlmostEqual(plan["target_reference"], 94)

    def test_stop_wins_if_stop_and_target_in_same_candle(self):
        result = evaluate_forward_path(100, [{"high": 106, "low": 96}], 97, 105, "LONG")
        self.assertEqual(result["outcome"], "STOP")

    def test_invalid_risk_inputs(self):
        self.assertIsNone(risk_plan(0, 2, "LONG"))


if __name__ == "__main__":
    unittest.main()
