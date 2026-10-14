import unittest

import core


class AlertQualityTests(unittest.TestCase):
    def setUp(self):
        self.volume = {
            "volume_ratio": 2.2,
            "price_move": 0.2,
            "buy_ratio": 0.62,
            "trend": "UP",
        }
        self.flow = {
            "inflow": 70.0,
            "outflow": 30.0,
            "netflow": 40.0,
            "source": "binance-taker",
        }
        self.oi = {"change_pct": 0.8}

    def test_early_alert_requires_volume_flow_oi_and_trend(self):
        self.assertTrue(core.early_watch(
            self.volume, {"volume": 1000}, self.flow, self.oi
        ))

    def test_early_alert_rejects_missing_oi_or_flow(self):
        self.assertFalse(core.early_watch(
            self.volume, {"volume": 1000}, self.flow, None
        ))
        self.assertFalse(core.early_watch(
            self.volume, {"volume": 1000}, None, self.oi
        ))

    def test_early_alert_rejects_flow_buy_ratio_disagreement(self):
        volume = dict(self.volume, buy_ratio=0.42)
        self.assertFalse(core.early_watch(
            volume, {"volume": 1000}, self.flow, self.oi
        ))

    def test_flat_market_metrics_confirm_neither_direction(self):
        snapshot = {
            "BTC.D": 50.0, "USDT.D": 5.0, "OTHERS.D": 10.0,
            "TOTAL": 1000.0, "TOTAL2": 500.0, "TOTAL3": 300.0,
        }
        result = core.market_alignment(snapshot, dict(snapshot))
        self.assertEqual(result["long"], 0)
        self.assertEqual(result["short"], 0)
        self.assertEqual(result["total"], 6)


if __name__ == "__main__":
    unittest.main()
