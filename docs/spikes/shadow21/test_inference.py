"""Run inside the benchmark image; no downloads or real inference."""

import unittest

import torch
from inference import Windowed


class WindowTests(unittest.TestCase):
    def test_silence_becomes_blank_and_windows_are_bounded(self):
        calls = []

        def fake(x):
            calls.append(x.shape[-1])
            return torch.ones((1, x.shape[-1] // 320 - 1, 4)), None

        wrapped = Windowed(fake, phone=False)
        wrapped.spans = [(16000, 496000), (496000, 656000)]
        result, _ = wrapped(torch.zeros(1, 75 * 16000))
        self.assertEqual(calls, [480000, 160000])
        self.assertEqual(result.shape, (1, 3750, 4))
        self.assertEqual(result[0, 0].argmax().item(), 0)
        self.assertTrue(torch.equal(result[0, 50], torch.ones(4)))
        self.assertEqual(result[0, -1].argmax().item(), 0)

    def test_all_silence_does_not_infer(self):
        wrapped = Windowed(lambda x: self.fail("silence inferred"), phone=False)
        wrapped.labels = 4
        result, _ = wrapped(torch.zeros(1, 16000))
        self.assertTrue(torch.all(result.argmax(-1) == 0))

    def test_phone_output_keeps_original_clock(self):
        from types import SimpleNamespace

        def fake(*, input_values):
            return SimpleNamespace(logits=torch.ones((1, 49, 4)))

        wrapped = Windowed(fake, phone=True)
        wrapped.spans = [(16000, 32000)]
        output = wrapped(input_values=torch.zeros(1, 48000)).logits
        self.assertEqual(output.shape, (1, 150, 4))
        self.assertEqual(output[0, 0].argmax().item(), 0)
        self.assertTrue(torch.equal(output[0, 50], torch.ones(4)))

    def test_silence_without_inventory_fails_explicitly(self):
        wrapped = Windowed(None, phone=False)
        with self.assertRaises(ValueError):
            wrapped(torch.zeros(1, 16000))
