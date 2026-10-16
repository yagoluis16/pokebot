"""Lifecycle regression tests using Events, without a live client."""
import threading
import unittest
from unittest.mock import Mock, patch

from modules import AutomationModule, ModuleState


class Probe(AutomationModule):
    def __init__(self, **kwargs):
        self.ready = threading.Event()
        self.entered = threading.Event()
        self.cleaned = threading.Event()
        self.cleanup_count = 0
        self.action = lambda: None
        super().__init__(Mock(), Mock(), "probe", interval=0.01, **kwargs)

    def setup(self):
        self.ready.set()

    def tick(self):
        self.entered.set()
        self.action()

    def teardown(self):
        self.cleanup_count += 1
        self.cleaned.set()


class AutomationModuleTests(unittest.TestCase):
    def test_disable_enable_and_restart(self):
        mod = Probe(enabled=False)
        self.addCleanup(mod.stop)
        self.assertTrue(mod.start())
        self.assertTrue(mod.ready.wait(1))
        self.assertEqual(mod.state, ModuleState.RUNNING_DISABLED)
        self.assertFalse(mod.entered.wait(0.04))
        mod.enable()
        self.assertTrue(mod.entered.wait(1))
        self.assertTrue(mod.stop())
        self.assertEqual(mod.state, ModuleState.STOPPED)
        self.assertEqual(mod.cleanup_count, 1)
        self.assertTrue(mod.stop())
        self.assertEqual(mod.cleanup_count, 1)
        self.assertTrue(mod.start())
        self.assertTrue(mod.stop())
        self.assertEqual(mod.cleanup_count, 2)

    def test_stop_timeout_preserves_worker_and_blocks_restart(self):
        mod = Probe()
        release = threading.Event()
        mod.action = release.wait
        try:
            mod.start()
            self.assertTrue(mod.entered.wait(1))
            worker = mod._thread
            with self.assertLogs(mod.log, level="WARNING"):
                self.assertFalse(mod.stop(timeout=0.01))
            self.assertTrue(mod.is_running)
            self.assertIs(mod._thread, worker)
            self.assertFalse(mod.start())
            self.assertEqual(mod.cleanup_count, 0)
        finally:
            release.set()
            self.assertTrue(mod.stop())
        self.assertEqual(mod.cleanup_count, 1)

    def test_error_limit_cleans_up_and_preserves_error_state(self):
        mod = Probe(max_errors=2)
        mod.action = Mock(side_effect=RuntimeError("expected test failure"))
        with self.assertLogs(mod.log, level="ERROR"):
            mod.start()
            self.assertTrue(mod.cleaned.wait(1))
            self.assertTrue(mod.stop())
        self.assertFalse(mod.is_running)
        self.assertEqual(mod.state, ModuleState.ERROR)
        self.assertEqual(mod.stats["errors"], 2)
        self.assertEqual(mod.cleanup_count, 1)

    def test_setup_failure_cleans_up(self):
        mod = Probe()
        mod.setup = Mock(side_effect=RuntimeError("setup failed"))
        with self.assertLogs(mod.log, level="ERROR"):
            self.assertTrue(mod.start())  # Launch succeeded; setup runs asynchronously.
            self.assertTrue(mod.cleaned.wait(1))
            self.assertTrue(mod.stop())
        self.assertEqual(mod.state, ModuleState.ERROR)
        self.assertEqual(mod.cleanup_count, 1)

    def test_stop_from_tick_does_not_join_itself(self):
        mod = Probe()
        mod.action = mod.stop
        mod.start()
        self.assertTrue(mod.cleaned.wait(1))
        self.assertTrue(mod.stop())
        self.assertEqual(mod.state, ModuleState.STOPPED)
        self.assertIsNone(mod.stats["last_error"])

    def test_thread_launch_failure(self):
        mod = Probe()
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("launch failed")), \
             self.assertLogs(mod.log, level="ERROR"):
            self.assertFalse(mod.start())
        self.assertFalse(mod.is_running)
        self.assertTrue(mod.stop())
        self.assertEqual(mod.state, ModuleState.ERROR)

    def test_registry_delegation(self):
        mod = Probe()
        mod.offsets.read.return_value = 179
        self.assertEqual(mod.read("player.hp"), 179)
        mod.offsets.read.assert_called_once_with(mod.memory, "player.hp")
        mod.entry("player.hp")
        mod.offsets.find.assert_called_once_with("player.hp")

    def test_invalid_interval_and_max_errors(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AutomationModuleTests.make_module(interval=value)
        with self.assertRaises(ValueError):
            Probe(max_errors=-1)

    @staticmethod
    def make_module(**kwargs):
        class Minimal(AutomationModule):
            def tick(self):
                return None
        return Minimal(None, None, "minimal", **kwargs)


if __name__ == "__main__":
    unittest.main()
