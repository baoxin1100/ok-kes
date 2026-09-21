# find_box_at_point：OCR 把按钮文字切成两个框时仍能找到按钮
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

from ok import Box  # noqa: E402
import utils  # noqa: E402

WIDTH, HEIGHT = 2145, 1207
# 繁中服「請選擇1張欲賦予靈光一閃的卡牌」页面卡住时的实际 OCR 结果：按钮被切成两个框，
# 中间的空隙正好压住按钮检测点 (0.945, 0.918)
SPLIT_BUTTON = (("跳過", 0.750, 0.792, 0.905, 0.947),
                ("賦予靈光-", 0.862, 0.941, 0.902, 0.949),
                ("一閃", 0.949, 0.973, 0.906, 0.944))


def text_box(name, x1, x2, y1, y2):
    # 与运行时一致：OCR 文本先经 _normalize_text 转为简体
    return Box(x1 * WIDTH, y1 * HEIGHT, to_x=x2 * WIDTH, to_y=y2 * HEIGHT, confidence=0.9,
               name=utils._normalize_text(name))


class FlashPageTask:
    """handle_flash 用到的任务接口。"""

    def __init__(self, boxes):
        self.width, self.height = WIDTH, HEIGHT
        self.config = {"游戏语言": "繁体中文"}
        self.all_texts = [text_box(*box) for box in boxes]
        self.clicked, self.logs = [], []

    def click_box(self, box, *args, **kwargs):
        self.clicked.append(box.name)

    def sleep(self, timeout):
        pass

    def log_info(self, message):
        self.logs.append(message)


class TestFindBoxAtPoint(unittest.TestCase):

    def setUp(self):
        self._is_button_active = utils.is_button_active

    def tearDown(self):
        utils.is_button_active = self._is_button_active

    def test_split_button_text_is_merged(self):
        task = FlashPageTask(SPLIT_BUTTON)
        box = utils.find_box_at_point(task, 0.945, 0.918)
        self.assertIsNotNone(box)
        self.assertIn("灵光一闪", box.name)  # 切开处的「-」已去掉
        self.assertLessEqual(box.x, int(0.862 * WIDTH) + 1)
        self.assertGreaterEqual(box.x + box.width, int(0.973 * WIDTH) - 1)

    def test_handle_flash_clicks_split_button(self):
        utils.is_button_active = lambda task, box: True  # 已选中卡牌，按钮可点
        task = FlashPageTask(SPLIT_BUTTON)
        self.assertTrue(utils.handle_flash(task))
        self.assertEqual(1, len(task.clicked))
        self.assertIn("灵光一闪", task.clicked[0])

    def test_inactive_split_button_is_not_clicked(self):
        utils.is_button_active = lambda task, box: False  # 还没选卡，按钮是灰色
        task = FlashPageTask(SPLIT_BUTTON)
        self.assertFalse(utils.handle_flash(task))
        self.assertEqual([], task.clicked)

    def test_box_containing_point_is_returned_unchanged(self):
        task = FlashPageTask((("賦予靈光一閃", 0.862, 0.973, 0.902, 0.949),))
        box = utils.find_box_at_point(task, 0.945, 0.918)
        self.assertIs(task.all_texts[0], box)

    def test_distant_texts_are_not_merged(self):
        task = FlashPageTask(SPLIT_BUTTON)
        self.assertIsNone(utils.find_box_at_point(task, 0.830, 0.925))  # 「跳過」与按钮之间
        self.assertIsNone(utils.find_box_at_point(task, 0.945, 0.700))  # 该行没有文字

    def test_no_texts(self):
        task = SimpleNamespace(width=WIDTH, height=HEIGHT, all_texts=[])
        self.assertIsNone(utils.find_box_at_point(task, 0.5, 0.5))


if __name__ == '__main__':
    unittest.main()
