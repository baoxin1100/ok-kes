import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import win32con

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ok.device.capture_methods.bitblt import BitBltCaptureMethod
from ok.device.capture_methods.base import BaseCaptureMethod
from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod
from ok.device.interaction_methods.post_message import PostMessageInteraction
from ok.task.TaskExecutor import TaskExecutor
from ok.task.exceptions import FinishedException, TaskDisabledException, WaitFailedException
from src import window_recovery as recovery


class ClockEvent:
    def __init__(self, clock):
        self.clock = clock
        self.stopped = False
        self.on_wait = None

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.clock.now += seconds
        if self.on_wait:
            self.on_wait()
        return self.stopped


class WindowRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recovery.install_window_recovery()

    def setUp(self):
        self.clock = SimpleNamespace(now=10.0)
        self.event = ClockEvent(self.clock)
        self.bounds = (100, 100, 1296, 759, 1280, 720, 1.0)
        self.minimized = False
        self.exists = True
        self.window = SimpleNamespace(hwnd=1, top_hwnd=1, width=1280, height=720,
                                      client_width=1280, client_height=720,
                                      monitors_bounds=[(0, 0, 2560, 1440)])
        self.method = object.__new__(BitBltCaptureMethod)
        self.method._hwnd_window = self.window
        self.method._size = (1280, 720)
        self.method.exit_event = self.event
        self.pixels = np.full((720, 1280, 3), 42, dtype=np.uint8)
        self.method.do_get_frame = Mock(return_value=self.pixels)
        self.interaction = PostMessageInteraction(self.method, self.window)
        self.manager = SimpleNamespace(capture_method=self.method, interaction=self.interaction)
        self.window.device_manager = self.manager
        self.executor = object.__new__(TaskExecutor)
        self.manager.executor = self.executor
        self.executor.device_manager = self.manager
        self.executor.config = {"supported_resolution": {"min_size": (1280, 720)}}
        self.executor.exit_event = self.event
        self.executor.thread = threading.current_thread()
        self.executor.paused = False
        self.executor.debug_mode = False
        self.executor.current_task = SimpleNamespace(_enabled=True, info_set=Mock())
        self.executor.scene = None
        self.executor._frame = None
        self.executor._last_frame_time = 0
        self.executor.blur_overlay_processor = None
        self.executor.wait_scene_timeout = 2
        self.executor.wait_until_settle_time = 0
        self.patches = [
            patch.object(recovery.time, "monotonic", side_effect=lambda: self.clock.now),
            patch.object(recovery.win32gui, "IsWindow", side_effect=lambda hwnd: self.exists),
            patch.object(recovery.win32gui, "IsIconic", side_effect=lambda hwnd: self.minimized),
            patch.object(recovery, "get_window_bounds", side_effect=lambda hwnd: self.bounds),
            patch.object(recovery.win32gui, "PostMessage"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.clear_context)

    def clear_context(self):
        recovery._context.window = None
        recovery._context.position_invalid = False

    def test_minimized_waits_then_restores_without_disabling_task(self):
        self.minimized = True
        def restore():
            if self.clock.now >= 40:
                self.minimized = False
        self.event.on_wait = restore
        frame = self.executor.next_frame(time_out=1)
        self.assertIs(frame, self.pixels)
        self.assertGreater(self.clock.now, 40)
        self.assertTrue(self.executor.current_task._enabled)
        self.assertFalse(self.executor.paused)
        self.method.do_get_frame.assert_called_once()

    def test_offscreen_waits_then_recovers(self):
        self.bounds = (-500, 100, 1296, 759, 1280, 720, 1)
        self.event.on_wait = lambda: setattr(self, "bounds", (100, 100, 1296, 759, 1280, 720, 1))
        self.assertIs(self.executor.next_frame(), self.pixels)
        self.assertFalse(self.executor.paused)

    def test_valid_move_discards_old_frame_and_reacquires(self):
        self.executor.next_frame()
        old_generation = self.executor._kes_frame_token
        self.bounds = (200, 100, 1296, 759, 1280, 720, 1)
        self.assertIs(self.executor.frame, self.pixels)
        self.assertNotEqual(old_generation, self.executor._kes_frame_token)
        self.assertEqual(self.method.do_get_frame.call_count, 2)

    def test_resized_frame_uses_new_dimensions(self):
        self.executor.next_frame()
        self.bounds = (100, 100, 1616, 939, 1600, 900, 1)
        self.window.client_width = self.window.width = 1600
        self.window.client_height = self.window.height = 900
        pixels = np.full((900, 1600, 3), 7, dtype=np.uint8)
        self.method.do_get_frame.return_value = pixels
        self.assertIs(self.executor.frame, pixels)
        self.assertEqual(self.method.width, 1600)

    def test_too_small_or_wrong_ratio_returns_no_frame(self):
        for width, height in [(640, 360), (1280, 800), (0, 0)]:
            self.bounds = (100, 100, width + 16, height + 39, width, height, 1)
            self.assertIsNone(self.method.get_frame())
        self.method.do_get_frame.assert_not_called()

    def test_minimized_capture_never_reuses_cached_pixels(self):
        self.executor.next_frame()
        self.minimized = True
        self.assertIsNone(self.method.get_frame())
        self.assertEqual(self.method.do_get_frame.call_count, 1)

    def test_transient_capture_failure_black_and_wrong_size_retry(self):
        self.method.do_get_frame.side_effect = [RuntimeError("device reset"), None,
            np.zeros((720, 1280, 3), np.uint8), np.ones((100, 100, 3), np.uint8), self.pixels]
        self.assertIs(self.executor.next_frame(time_out=0.1), self.pixels)
        self.assertEqual(self.method.do_get_frame.call_count, 5)
        self.assertTrue(self.executor.current_task._enabled)

    def test_geometry_changes_during_capture_discard_frame(self):
        def capture():
            if self.method.do_get_frame.call_count == 1:
                self.bounds = (200, 100, 1296, 759, 1280, 720, 1)
            return self.pixels
        self.method.do_get_frame.side_effect = capture
        self.assertIs(self.executor.next_frame(), self.pixels)
        self.assertEqual(self.method.do_get_frame.call_count, 2)

    def test_stop_interrupts_wait_without_task_error(self):
        self.minimized = True
        self.event.on_wait = lambda: setattr(self.event, "stopped", True)
        with self.assertRaises(FinishedException):
            self.executor.next_frame()
        self.method.do_get_frame.assert_not_called()

    def test_disable_task_interrupts_recovery_wait(self):
        self.minimized = True
        self.event.on_wait = lambda: setattr(self.executor.current_task, "_enabled", False)
        with self.assertRaises(TaskDisabledException):
            self.executor.next_frame()

    def test_only_window_position_pause_is_intercepted(self):
        recovery._context.window = self.window
        recovery.hwnd_module.check_pos(-500, 100, 1280, 720, self.window.monitors_bounds)
        self.assertFalse(self.executor.pause())
        self.assertFalse(self.executor.paused)
        self.clear_context()
        self.assertTrue(self.executor.pause())
        self.assertTrue(self.executor.paused)
        # Position recovery must never call start() to undo the manual pause.
        self.assertIsNone(self.method.get_frame())
        self.assertTrue(self.executor.paused)

    def test_actual_game_exit_pause_is_preserved(self):
        recovery._context.window = self.window
        recovery._context.position_invalid = False
        self.assertTrue(self.executor.pause())

    def test_native_window_monitor_position_loss_does_not_pause_or_notify_error(self):
        window = object.__new__(recovery.hwnd_module.HwndWindow)
        window.__dict__.update(vars(self.window))
        window.__dict__.update(dict(visible=False, x=100, y=100, window_width=1296, window_height=759,
            scaling=1, real_x_offset=0, real_y_offset=0, real_width=0, real_height=0,
            title="test", exe_names=["test.exe"], frame_width=1280, frame_height=720,
            frame_aspect_ratio=16/9, player_id=-1, hwnd_class=None, top_hwnd_class=None,
            pos_valid=True, exists=True, last_mute_check=recovery.time.time(), visible_monitors=[]))
        self.method._hwnd_window = window
        self.manager.config = {}
        self.manager.get_preferred_device = Mock(return_value=None)
        notifications = SimpleNamespace(notification=Mock(), window=Mock(), adb_devices=Mock())
        with patch.object(recovery.hwnd_module, "find_hwnd", return_value=(
            "test", 1, "test.exe", 0, 0, 0, 0, [(1, "test.exe", 1280, 720, 100, 100)])), \
             patch.object(recovery.hwnd_module.HwndWindow, "is_foreground", return_value=False), \
             patch.object(recovery.hwnd_module, "get_window_bounds", return_value=(-32000, -32000, 0, 0, 0, 0, 1)), \
             patch.object(recovery.hwnd_module, "communicate", notifications), \
             patch.object(recovery.hwnd_module.logger, "error") as error:
            window.do_update_window_size()
        self.assertFalse(window.pos_valid)
        self.assertFalse(self.executor.paused)
        notifications.notification.emit.assert_not_called()
        error.assert_not_called()

    def test_wgc_uses_the_same_recovery_and_frame_validation(self):
        method = object.__new__(WindowsGraphicsCaptureMethod)
        method._hwnd_window = self.window
        method._size = (1280, 720)
        method.exit_event = self.event
        method.do_get_frame = Mock(return_value=self.pixels)
        self.manager.capture_method = method
        self.manager.interaction = PostMessageInteraction(method, self.window)
        self.minimized = True
        self.event.on_wait = lambda: setattr(self, "minimized", False)
        self.assertIs(self.executor.next_frame(), self.pixels)
        method.do_get_frame.assert_called_once()

    def test_stale_click_is_dropped_until_new_frame(self):
        self.executor.next_frame()
        self.interaction.post(win32con.WM_LBUTTONDOWN)
        self.assertEqual(recovery.win32gui.PostMessage.call_count, 1)
        self.bounds = (200, 100, 1296, 759, 1280, 720, 1)
        self.interaction.post(win32con.WM_LBUTTONDOWN)
        self.assertEqual(recovery.win32gui.PostMessage.call_count, 1)
        self.executor.next_frame()
        self.interaction.post(win32con.WM_LBUTTONDOWN)
        self.assertEqual(recovery.win32gui.PostMessage.call_count, 2)

    def test_minimized_and_paused_input_blocked_but_button_release_allowed(self):
        self.executor.next_frame()
        self.minimized = True
        for msg in [win32con.WM_LBUTTONDOWN, win32con.WM_KEYDOWN, win32con.WM_MOUSEMOVE]:
            self.interaction.post(msg)
        recovery.win32gui.PostMessage.assert_not_called()
        self.interaction.post(win32con.WM_LBUTTONUP)
        recovery.win32gui.PostMessage.assert_called_once()
        self.minimized = False
        self.executor.next_frame()
        self.executor.paused = True
        self.interaction.post(win32con.WM_LBUTTONDOWN)
        self.assertEqual(recovery.win32gui.PostMessage.call_count, 1)

    def test_capture_loss_invalidates_clicks_even_without_geometry_change(self):
        self.executor.next_frame()
        self.method.do_get_frame.return_value = None
        self.assertIsNone(self.method.get_frame())
        self.interaction.post(win32con.WM_LBUTTONDOWN)
        recovery.win32gui.PostMessage.assert_not_called()
        self.method.do_get_frame.return_value = self.pixels
        self.executor.next_frame()
        self.interaction.post(win32con.WM_LBUTTONDOWN)
        recovery.win32gui.PostMessage.assert_called_once()

    def test_window_wait_does_not_exhaust_wait_until_timeout(self):
        self.minimized = True
        self.event.on_wait = lambda: setattr(self, "minimized", False) if self.clock.now > 40 else None
        condition = Mock(side_effect=[False, "found"])
        self.assertEqual(self.executor.wait_condition(condition, time_out=1, raise_if_not_found=True), "found")
        self.assertGreater(recovery._guard(self.method).total_wait, 30)

    def test_normal_wait_until_timeout_still_raises(self):
        def condition():
            self.clock.now += 1
            return False
        with self.assertRaises(WaitFailedException):
            self.executor.wait_condition(condition, time_out=1, raise_if_not_found=True)

    def test_other_capture_methods_are_untouched(self):
        method = BaseCaptureMethod()
        method.exit_event = self.event
        method.do_get_frame = Mock(return_value=self.pixels)
        self.assertIs(method.get_frame(), self.pixels)

    def test_installer_is_idempotent(self):
        previous = TaskExecutor.next_frame
        recovery.install_window_recovery()
        self.assertIs(TaskExecutor.next_frame, previous)


if __name__ == "__main__":
    unittest.main()
