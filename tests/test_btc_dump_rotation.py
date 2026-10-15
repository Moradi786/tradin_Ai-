import unittest
from unittest.mock import patch

import core
import premove


class BtcDumpRotationTests(unittest.TestCase):
    def setUp(self):
        self.volume = {
            "volume_ratio": 1.6,
            "price_move": 0.4,
            "buy_ratio": 0.62,
            "trend": "UP",
        }
        self.flow = {
            "inflow": 70.0,
            "outflow": 30.0,
            "netflow": 40.0,
        }
        self.oi = {"change_pct": 0.8}
        self.market = {"long_details": {"BTC.D": True}}
        self.tickers = {
            "ALTUSDT": {"priceChangePercent": 3.0},
            "BTCUSDT": {"priceChangePercent": -2.0},
        }

    def detect(self, volume=None, flow=None, oi=None, market=None):
        with patch.multiple(
            premove,
            BTCDUMP_ENABLED=True,
            BTCDUMP_BTC_MAX=-0.5,
            BTCDUMP_REL_MIN=1.0,
            BTCDUMP_VOLUME_MIN=1.3,
            PREMOVE_OI_MIN=0.5,
            PREMOVE_FLOW_RATIO=0.05,
        ), patch.object(core, "REQUIRE_TREND", True), patch.dict(
            core.tickers_cache, {"data": self.tickers}
        ):
            return premove.detect_btc_dump(
                "ALTUSDT",
                self.volume if volume is None else volume,
                self.flow if flow is None else flow,
                self.oi if oi is None else oi,
                self.market if market is None else market,
            )

    def test_alerts_when_btc_and_btc_d_fall_and_alt_outperforms(self):
        result = self.detect()
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "BULLISH")
        self.assertAlmostEqual(result["rel_btc"], ((1.03 / 0.98) - 1) * 100.0)

    def test_rejects_weak_buy_pressure(self):
        volume = dict(self.volume, buy_ratio=0.49)
        self.assertIsNone(self.detect(volume=volume))

    def test_rejects_when_btc_d_is_not_falling(self):
        self.assertIsNone(self.detect(market={"long_details": {"BTC.D": False}}))


if __name__ == "__main__":
    unittest.main()
