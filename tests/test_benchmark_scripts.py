import unittest

from scripts import benchmark_dialog, benchmark_repeat


class BenchmarkScriptTests(unittest.TestCase):
    def test_run_id_accepts_exact_hex_and_normalizes_case(self):
        self.assertEqual(benchmark_dialog._resolve_run_id("A1B2C3D4"), "a1b2c3d4")

    def test_run_id_rejects_invalid_value(self):
        for value in ("abc", "abcdefgh", "123456789", "12-45678"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    benchmark_dialog._resolve_run_id(value)

    def test_percentile_uses_linear_interpolation(self):
        values = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(benchmark_repeat._percentile(values, 0.50), 25.0)
        self.assertAlmostEqual(benchmark_repeat._percentile(values, 0.95), 38.5)

    def test_scenario_summary_reports_pass_rate_and_latency_statistics(self):
        runs = [
            {
                "scenario_results": [
                    {
                        "id": "scenario-a",
                        "category": "deterministic",
                        "passed": True,
                        "client_total_ms": 100.0,
                    }
                ]
            },
            {
                "scenario_results": [
                    {
                        "id": "scenario-a",
                        "category": "deterministic",
                        "passed": False,
                        "client_total_ms": 300.0,
                    }
                ]
            },
        ]

        summary = benchmark_repeat._scenario_summary(runs)

        self.assertEqual(len(summary), 1)
        row = summary[0]
        self.assertEqual(row["runs"], 2)
        self.assertEqual(row["passes"], 1)
        self.assertEqual(row["pass_rate_pct"], 50.0)
        self.assertEqual(row["avg_client_total_ms"], 200.0)
        self.assertEqual(row["median_client_total_ms"], 200.0)
        self.assertEqual(row["p95_client_total_ms"], 290.0)
        self.assertAlmostEqual(row["stddev_client_total_ms"], 141.421, places=3)


if __name__ == "__main__":
    unittest.main()
