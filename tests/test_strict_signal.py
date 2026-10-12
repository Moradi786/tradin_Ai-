import unittest

import core


class StrictSignalQualityTests(unittest.TestCase):
    def test_long_atr_levels_are_suggestions_with_two_to_one_rr(self):
        levels = core.apply_atr_risk_levels("LONG", {"price": 100, "atr": 2})
        self.assertAlmostEqual(levels["stop_loss"], 97)
        self.assertAlmostEqual(levels["take_profit"], 106)
        self.assertEqual(levels["rr"], 2.0)

    def test_short_atr_levels_reverse_direction(self):
        levels = core.apply_atr_risk_levels("SHORT", {"price": 100, "atr": 2})
        self.assertAlmostEqual(levels["stop_loss"], 103)
        self.assertAlmostEqual(levels["take_profit"], 94)

    def test_missing_atr_disables_risk_levels(self):
        self.assertEqual(core.apply_atr_risk_levels("LONG", {"price": 100}), {})

    def test_five_of_six_can_reach_90_only_when_sweep_is_missing(self):
        result = core.strict_signal_quality(
            "LONG",
            {"15m": 20, "1h": 30, "4h": 40},
            {"volume_ratio": 3, "buy_ratio": 0.7},
            {"inflow": 70, "outflow": 30, "netflow": 40},
            {"direction": "BULLISH"},
            {"long": 5, "score": 90},
            {"change_pct": 1.0},
            {"trends": {"15m": "UP", "1h": "UP", "4h": "UP"},
             "structure": "BULLISH", "sweep": "NONE"},
        )
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["score"], 90)
        self.assertTrue(result["mandatory"])

    def test_missing_timeframe_trend_fails_mandatory_gate(self):
        result = core.strict_signal_quality(
            "LONG",
            {"15m": 20, "1h": 30, "4h": 40},
            {"volume_ratio": 3, "buy_ratio": 0.7},
            {"inflow": 70, "outflow": 30, "netflow": 40},
            {"direction": "BULLISH"},
            {"long": 5, "score": 90},
            {"change_pct": 1.0},
            {"trends": {"15m": "UP", "1h": "UNKNOWN", "4h": "UP"},
             "structure": "BULLISH", "sweep": "NONE"},
        )
        self.assertFalse(result["mandatory"])
        self.assertFalse(result["groups"]["multi_timeframe_trend"])


if __name__ == "__main__":
    unittest.main()
