import unittest

from sd import runtime_guard


class RuntimeGuardTests(unittest.TestCase):
    def test_detects_existing_inference(self):
        info = runtime_guard.snapshot(
            "MemTotal: 131072000 kB\nMemAvailable: 90000000 kB\nSwapTotal: 0 kB\n",
            "1.00 0.5 0.2 1/1 1", "python infer.py --prompts x")
        self.assertIn("已有", runtime_guard.start_blocker(info, 48))

    def test_detects_low_unified_memory_headroom(self):
        info = runtime_guard.snapshot(
            "MemTotal: 131072000 kB\nMemAvailable: 30000000 kB\nSwapTotal: 0 kB\n",
            "1.00 0.5 0.2 1/1 1", "")
        self.assertIn("可用统一内存", runtime_guard.start_blocker(info, 48))

    def test_allows_one_clean_start(self):
        info = runtime_guard.snapshot(
            "MemTotal: 131072000 kB\nMemAvailable: 90000000 kB\nSwapTotal: 0 kB\n",
            "1.00 0.5 0.2 1/1 1", "")
        self.assertIsNone(runtime_guard.start_blocker(info, 48))


if __name__ == "__main__":
    unittest.main()
