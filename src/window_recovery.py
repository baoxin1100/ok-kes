"""Recover from transient PC window/capture loss without disabling tasks.

Applies only to background WGC/BitBlt + PostMessage. Minimized windows cannot
reliably provide fresh frames, so wait for restoration instead of using a cache.
Framework integration lives here rather than modifying site-packages.
"""
import functools
import threading
import time

import win32con
import win32gui

from ok.device.capture_methods import hwnd_window as hwnd_module
from ok.device.capture_methods.base import BaseCaptureMethod
from ok.device.capture_methods.bitblt import BitBltCaptureMethod
from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod
from ok.device.interaction_methods.post_message import PostMessageInteraction
from ok.task.TaskExecutor import TaskExecutor
from ok.task.exceptions import CaptureException, FinishedException, WaitFailedException
from ok.util.logger import Logger
from ok.util.window import get_window_bounds

logger = Logger.get_logger(__name__)
_context = threading.local()
_native_check_pos = hwnd_module.check_pos
_POLL_SECONDS = 0.1
_SETTLE_SECONDS = 0.4


def _background_method(method):
    if not isinstance(method, (WindowsGraphicsCaptureMethod, BitBltCaptureMethod)):
        return False
    manager = getattr(method.hwnd_window, "device_manager", None)
    return (manager is not None and manager.capture_method is method
            and type(getattr(manager, "interaction", None)) is PostMessageInteraction)


class WindowGuard:
    def __init__(self, window):
        self.window = window
        self.lock = threading.RLock()
        self.signature = None
        self.changed_at = 0
        self.generation = 0
        self.total_wait = 0.0
        self.notice = ""
        self.frame_lost = False

    def invalidate_frame(self):
        with self.lock:
            if not self.frame_lost:
                self.frame_lost = True
                self.generation += 1

    def probe(self):
        window = self.window
        with self.lock:
            hwnd = window.hwnd
            try:
                exists = bool(hwnd and win32gui.IsWindow(hwnd))
                minimized = exists and (win32gui.IsIconic(hwnd) or (
                    window.top_hwnd and win32gui.IsIconic(window.top_hwnd)))
                bounds = get_window_bounds(hwnd) if exists and not minimized else None
            except win32gui.error:
                exists, minimized, bounds = False, False, None
            signature = (hwnd, window.top_hwnd, bool(minimized), bounds)
            now = time.monotonic()
            if signature != self.signature:
                self.signature = signature
                self.changed_at = now
                self.generation += 1
            if not exists:
                return False, "游戏窗口暂不可用，等待窗口恢复"
            if minimized:
                return False, "游戏窗口已最小化，等待还原"
            x, y, _, _, width, height, _ = bounds
            if width <= 0 or height <= 0:
                return False, "游戏窗口没有有效画面，等待恢复"
            if not _native_check_pos(x, y, width, height, window.monitors_bounds):
                return False, "游戏窗口部分位于屏幕外，等待移回屏幕"
            executor = getattr(window.device_manager, "executor", None)
            resolution = (getattr(executor, "config", None) or {}).get("supported_resolution", {})
            minimum = resolution.get("min_size", (1280, 720))
            if width < minimum[0] or height < minimum[1] or abs(width / height - 16 / 9) > 0.02:
                return False, f"等待游戏窗口恢复为16:9且不小于{minimum[0]}×{minimum[1]}"
            if now - self.changed_at < _SETTLE_SECONDS or (
                    window.client_width != width or window.client_height != height):
                return False, "窗口正在移动或缩放，等待画面稳定"
            return True, ""

    def show_wait(self, executor, reason):
        if self.notice != reason:
            self.notice = reason
            logger.info(reason)
            if executor.current_task is not None:
                executor.current_task.info_set("窗口状态", reason)

    def recovered(self, executor):
        self.frame_lost = False
        if self.notice:
            self.notice = ""
            logger.info("游戏窗口画面已恢复，重新识别后继续运行")
            if executor.current_task is not None:
                executor.current_task.info_set("窗口状态", "画面已恢复，继续运行")


def _guard(method):
    window = method.hwnd_window
    if not hasattr(window, "_kes_window_guard"):
        window._kes_window_guard = WindowGuard(window)
    return window._kes_window_guard


def _executor_method(executor):
    method = executor.method
    return method if _background_method(method) else None


def _wait_tick(executor, guard, reason):
    guard.show_wait(executor, reason)
    start = time.monotonic()
    try:
        # Framework pause/disable/exit semantics are preserved. Never call
        # executor.start(): restoring a window must not undo a manual pause.
        executor.check_enabled()
        if executor.exit_event.wait(_POLL_SECONDS):
            raise FinishedException()
    finally:
        guard.total_wait += time.monotonic() - start


def _next_frame(executor, original, time_out):
    method = _executor_method(executor)
    if method is None or not executor.is_executor_thread():
        return original(executor, time_out=time_out)
    guard = _guard(method)
    executor.reset_scene()
    while not executor.exit_event.is_set():
        if executor.method is not method:
            return executor.next_frame(time_out=time_out)
        executor.check_enabled()
        ready, reason = guard.probe()
        if not ready:
            _wait_tick(executor, guard, reason)
            continue
        generation = guard.generation
        start = time.monotonic()
        frame = method.get_frame()
        if executor.paused:
            executor.check_enabled()
            continue  # A frame captured before a manual pause is now stale.
        executor.check_enabled()
        ready, reason = guard.probe()
        if frame is None or not ready or generation != guard.generation:
            guard.total_wait += time.monotonic() - start
            _wait_tick(executor, guard, reason or "暂时获取不到有效游戏画面，等待恢复")
            continue
        executor._frame = frame
        executor._last_frame_time = time.time()
        executor._kes_frame_token = (method, generation)
        if executor.blur_overlay_processor:
            executor.blur_overlay_processor.next_frame(frame)
        guard.recovered(executor)
        return frame
    raise FinishedException()


def _wait_condition(executor, condition, time_out=0, pre_action=None, post_action=None,
                    settle_time=-1, raise_if_not_found=False):
    """Use active time so a minimized window cannot exhaust a task's wait timer."""
    guard = _guard(executor.method)
    executor.reset_scene()
    started = time.monotonic()
    waited = guard.total_wait
    timeout = time_out or executor.wait_scene_timeout
    settled = None
    last_wait = waited
    while not executor.exit_event.is_set():
        if pre_action is not None:
            pre_action()
        executor.next_frame()
        if guard.total_wait != last_wait:
            settled = None
            last_wait = guard.total_wait
        result = condition()
        active_time = time.monotonic() - started - (guard.total_wait - waited)
        if result:
            settle = executor.wait_until_settle_time if settle_time == -1 else settle_time
            if settle <= 0:
                return result
            if settled is not None and active_time - settled > settle:
                return result
            if settled is None:
                settled = active_time
            continue
        else:
            settled = None
        if post_action is not None and not result:
            post_action()
        if active_time > timeout:
            break
    if executor.exit_event.is_set():
        raise FinishedException()
    if raise_if_not_found:
        raise WaitFailedException()


def install_window_recovery():
    if getattr(TaskExecutor, "_kes_window_recovery_installed", False):
        return
    original_update = hwnd_module.HwndWindow.do_update_window_size
    original_check_pos = hwnd_module.check_pos
    original_pause = TaskExecutor.pause
    original_frame = TaskExecutor.frame
    original_next = TaskExecutor.next_frame
    original_wait = TaskExecutor.wait_condition
    original_capture = BaseCaptureMethod.get_frame
    original_post = PostMessageInteraction.post

    @functools.wraps(original_update)
    def update(window):
        previous = getattr(_context, "window", None)
        previous_invalid = getattr(_context, "position_invalid", False)
        _context.window, _context.position_invalid = window, False
        try:
            return original_update(window)
        finally:
            _context.window, _context.position_invalid = previous, previous_invalid

    @functools.wraps(original_check_pos)
    def check_pos(*args, **kwargs):
        valid = original_check_pos(*args, **kwargs)
        _context.position_invalid = not valid
        return valid

    @functools.wraps(original_pause)
    def pause(executor, task=None):
        window = getattr(_context, "window", None)
        if (task is None and window is not None and getattr(_context, "position_invalid", False)
                and _executor_method(executor) is not None and executor.method.hwnd_window is window):
            # Only intercept the framework's position-loss pause, in its own
            # window-monitor thread. Manual pauses and actual game exit keep
            # their native behavior.
            return False
        return original_pause(executor, task)

    @functools.wraps(original_capture)
    def capture(method):
        if not _background_method(method):
            return original_capture(method)
        guard = _guard(method)
        ready, _ = guard.probe()
        if not ready:
            return None
        generation = guard.generation
        try:
            frame = original_capture(method)
        except CaptureException:
            if not guard.frame_lost:
                logger.debug("游戏截图暂时失败，等待重新获取画面")
            guard.invalidate_frame()
            return None
        ready, _ = guard.probe()
        if not ready or generation != guard.generation:
            return None
        if frame is None or not frame.any():
            guard.invalidate_frame()
            return None
        if frame.shape[1] != method.hwnd_window.width or frame.shape[0] != method.hwnd_window.height:
            guard.invalidate_frame()
            return None
        return frame

    @functools.wraps(original_next)
    def next_frame(executor, time_out=6):
        return _next_frame(executor, original_next, time_out)

    def frame(executor):
        method = _executor_method(executor)
        if method is not None and executor.is_executor_thread():
            guard = _guard(method)
            ready, _ = guard.probe()
            if not ready or getattr(executor, "_kes_frame_token", None) != (method, guard.generation):
                executor._frame = None
        return original_frame.fget(executor)

    @functools.wraps(original_wait)
    def wait_condition(executor, *args, **kwargs):
        if _executor_method(executor) is not None and executor.is_executor_thread():
            return _wait_condition(executor, *args, **kwargs)
        return original_wait(executor, *args, **kwargs)

    @functools.wraps(original_post)
    def post(interaction, message, wParam=0, lParam=0, hwnd=None):
        method = interaction.capture
        releases = {win32con.WM_LBUTTONUP, win32con.WM_RBUTTONUP,
                    win32con.WM_MBUTTONUP, win32con.WM_KEYUP}
        if _background_method(method) and message not in releases:
            guard = _guard(method)
            executor = method.hwnd_window.device_manager.executor
            ready, reason = guard.probe()
            if (executor is None or executor.paused or executor.exit_event.is_set() or
                    (executor.current_task is not None and not executor.current_task._enabled) or not ready or
                    getattr(executor, "_kes_frame_token", None) != (method, guard.generation)):
                if executor is not None:
                    executor._frame = None
                    guard.show_wait(executor, reason or "画面已变化，等待重新识别")
                return
        return original_post(interaction, message, wParam, lParam, hwnd)

    hwnd_module.HwndWindow.do_update_window_size = update
    hwnd_module.check_pos = check_pos
    TaskExecutor.pause = pause
    TaskExecutor.next_frame = next_frame
    TaskExecutor.frame = property(frame, original_frame.fset, original_frame.fdel)
    TaskExecutor.wait_condition = wait_condition
    BaseCaptureMethod.get_frame = capture
    PostMessageInteraction.post = post
    TaskExecutor._kes_window_recovery_installed = True
