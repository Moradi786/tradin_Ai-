import unittest
from unittest.mock import patch

import core
import premove


class ConservativePreMoveTests(unittest.TestCase):
    def setUp(self):
        self.volume = {
            "price": 99.5,
            "volume_ratio": 1.5,
            "price_move": 0.2,
            "buy_ratio": 0.62,
            "trend": "UP",
            "closes": [99.0] * 30,
            "highs": [100.0] * 12,
            "lows": [95.0] * 12,
        }
        self.flow = {"inflow": 70.0, "outflow": 30.0, "netflow": 40.0}
        self.oi = {"change_pct": 0.8}

    def detect(self, volume=None, trend_required=True):
        with patch.multiple(
            premove,
            PREMOVE_ENABLED=True,
            PREMOVE_VOLUME_MIN=1.2,
            PREMOVE_VOLUME_MAX=2.5,
            PREMOVE_MAX_PRICE_MOVE=0.8,
            PREMOVE_OI_MIN=0.5,
            PREMOVE_FLOW_RATIO=0.05,
            PREMOVE_MIN_SCORE=4,
            PREMOVE_LEVEL_LOOKBACK=12,
            PREMOVE_LEVEL_DISTANCE_PCT=1.0,
        ), patch.object(core, "REQUIRE_TREND", trend_required), patch.object(
            premove, "rsi", side_effect=[55.0, 52.0]
        ):
            return premove.detect_premove(
                "ALTUSDT", self.volume if volume is None else volume,
                self.flow, self.oi
            )

    def test_long_near_resistance_before_breakout_is_flagged(self):
        result = self.detect()
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "BULLISH")
        self.assertEqual(result["setup"], "NEAR_BREAKOUT")

    def test_rejects_price_far_from_breakout_level(self):
        volume = dict(self.volume, price=97.0)
        self.assertIsNone(self.detect(volume=volume))

    def test_rejects_already_expanded_volume_candle(self):
        volume = dict(self.volume, volume_ratio=3.0)
        self.assertIsNone(self.detect(volume=volume))

    def test_requires_trend_alignment_in_conservative_mode(self):
        volume = dict(self.volume, trend="DOWN")
        self.assertIsNone(self.detect(volume=volume))


if __name__ == "__main__":
    unittest.main()
