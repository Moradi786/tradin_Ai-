import unittest
from unittest.mock import patch

import core
import premove


class RotationSignalQualityTests(unittest.TestCase):
    def setUp(self):
        self.volume = {
            "volume_ratio": 1.5,
            "price_move": 0.2,
            "buy_ratio": 0.62,
            "trend": "UP",
        }
        self.flow = {"inflow": 70.0, "outflow": 30.0, "netflow": 40.0}
        self.oi = {"change_pct": 0.8}
        self.market = {
            "long_details": {"BTC.D": True, "USDT.D": True},
            "short_details": {"USDT.D": False},
        }
        self.tickers = {
            "ALTUSDT": {"priceChangePercent": 3.0},
            "BTCUSDT": {"priceChangePercent": 2.0},
        }

    def detect(self, market=None):
        with patch.multiple(
            premove,
            ROTATION_ENABLED=True,
            ROTATION_REL_MIN=0.5,
            ROTATION_REL_MAX=8.0,
            ROTATION_ALT_MAX_24H=8.0,
            PREMOVE_VOLUME_MIN=1.2,
            PREMOVE_MAX_PRICE_MOVE=0.8,
            PREMOVE_OI_MIN=0.5,
            PREMOVE_FLOW_RATIO=0.05,
        ), patch.object(core, "REQUIRE_TREND", True), patch.dict(
            core.tickers_cache, {"data": self.tickers}
        ):
            return premove.detect_rotation(
                "ALTUSDT", self.volume, self.flow, self.oi,
                self.market if market is None else market,
            )

    def test_uses_actual_alt_btc_pair_return(self):
        result = self.detect()
        self.assertIsNotNone(result)
        expected = ((1.03 / 1.02) - 1.0) * 100.0
        self.assertAlmostEqual(result["rel_btc"], expected)
        self.assertEqual(result["alt_change"], 3.0)
        self.assertEqual(result["btc_change"], 2.0)

    def test_rejects_rotation_when_usdt_dominance_is_rising(self):
        market = {
            "long_details": {"BTC.D": True},
            "short_details": {"USDT.D": True},
        }
        self.assertIsNone(self.detect(market=market))


if __name__ == "__main__":
    unittest.main()
