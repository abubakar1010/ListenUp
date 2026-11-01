import unittest

from core import pack, summary, windows


class BenchmarkTests(unittest.TestCase):
    def test_pack_uses_whole_utterances_and_never_repeats(self):
        rounds = pack([(str(i), 4.0) for i in range(600)], count=30)
        self.assertEqual(len(rounds), 30)
        self.assertTrue(all(75 <= sum(d for _, d in r) < 79 for r in rounds))
        names = [name for r in rounds for name, _ in r]
        self.assertEqual(len(names), len(set(names)))

    def test_pack_rejects_insufficient_data(self):
        with self.assertRaises(ValueError):
            pack([("one", 3.0)], count=30)

    def test_windows_skip_silence_and_bound_work(self):
        self.assertEqual(
            windows([{"start": 16000, "end": 1040000}], 16000),
            [(16000, 496000), (496000, 976000), (976000, 1040000)],
        )
        self.assertEqual(windows([], 16000), [])

    def test_summary_requires_all_30_and_uses_nearest_rank(self):
        report = summary(list(range(1, 31)))
        self.assertEqual(report["p50_s"], 15)
        self.assertEqual(report["p95_s"], 29)
        self.assertEqual(report["range_s"], [1, 30])
        self.assertTrue(report["pass"])
        self.assertFalse(summary([50] * 30)["pass"])
        for invalid in [[], [1] * 29, [float("nan")] * 30, [-1] * 30]:
            with self.assertRaises(ValueError):
                summary(invalid)


if __name__ == "__main__":
    unittest.main()
