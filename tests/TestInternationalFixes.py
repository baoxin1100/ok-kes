# 繁中服（国际服）页面修正：BOSS 选择页标题、休息区读不到生命值/信用点、休息后等「確認」
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

from ok import Box  # noqa: E402
import utils  # noqa: E402
import utils_sortie  # noqa: E402

WIDTH, HEIGHT = 2560, 1440
BOSS_POINTS = ["(0.358, 0.706)", "(0.641, 0.706)"]
REST_READ_RETRIES = getattr(utils, "_REST_READ_RETRIES", 3)


def text(name, cx, cy, w=0.06, h=0.03, raw=False):
    """中心在 (cx, cy) 的文字框。主循环的 OCR 结果会经 _simplify_texts 转为简体；raw=True 表示不转（如 wait_ocr）。"""
    return Box((cx - w / 2) * WIDTH, (cy - h / 2) * HEIGHT, to_x=(cx + w / 2) * WIDTH, to_y=(cy + h / 2) * HEIGHT,
               confidence=0.9, name=name if raw else utils._normalize_text(name))


class PageTask:
    """页面处理函数用到的任务接口；文字、模板匹配结果、确认按钮由用例指定。"""
    name = "测试"

    def __init__(self, texts, features=(), confirm=()):
        self.width, self.height = WIDTH, HEIGHT
        self.config = {"游戏语言": "繁体中文", "生命值大于多少优先闪光(百分比)": "60", "多少信用点以上冥想": 100}
        self.node_status = {"flash_or_rest": True, "shop": False}
        self.member_status = {"deck": {"冥想": {"剑雨": True}}}
        self.all_texts = [text(*t) for t in texts]
        self.features = {name: text(name, x, y) for name, x, y in features}
        self.confirm = [text(c, 0.570, 0.669, raw=True) for c in confirm]  # wait_ocr 的原始结果（不转简体）
        self.clicked, self.logs = [], []

    def show(self, texts):
        """下一帧：页面上的文字变成 texts。"""
        self.all_texts = [text(*t) for t in texts]

    def wait_ocr(self, *args, match=None, time_out=0, **kwargs):
        return [b for b in self.confirm if match.search(b.name)]

    def find_one(self, feature_name=None, box=None, threshold=0, **kwargs):
        return self.features.get(feature_name)

    def box_of_screen(self, x, y, to_x=1.0, to_y=1.0, **kwargs):
        return Box(x * WIDTH, y * HEIGHT, to_x=to_x * WIDTH, to_y=to_y * HEIGHT)

    def click_box(self, box=None, *args, **kwargs):
        self.clicked.append(box.name)

    def click(self, x=-1, y=-1, *args, **kwargs):
        self.clicked.append(f"({x:.3f}, {y:.3f})")

    def move_relative(self, x, y):
        pass

    def sleep(self, timeout):
        pass

    def log_info(self, message):
        self.logs.append(message)


# 出击模式休息区：闪光（费用 20）和免费休息都可选
SORTIE_REST = [("閃光", 0.83, 0.50), ("20", 0.83, 0.55), ("免費", 0.25, 0.70)]
SORTIE_FEATURES = [("flash_in_sortie_safezoom", 0.83, 0.50), ("rest", 0.30, 0.70)]
# 卡厄思模式休息区：免费休息和冥想（费用 50）都可选
CHAOS_REST = [("免費", 0.25, 0.70), ("50", 0.80, 0.70)]
CHAOS_FEATURES = [("rest", 0.30, 0.70), ("meditate", 0.80, 0.60)]
CREDIT = ("300", 0.794, 0.054)


def hp(current, maximum=1200):
    return (f"{current}/{maximum}", 0.209, 0.040)


class TestBossSelection(unittest.TestCase):

    def test_traditional_title_selects_a_boss(self):
        task = PageTask([("請選擇在核心遭遇的BOSS。", 0.484, 0.928, 0.25), ("靈魂收割者", 0.358, 0.706, 0.10),
                         ("瘟神", 0.641, 0.706)])
        self.assertTrue(utils_sortie.handle_boss_selection(task))
        self.assertEqual(1, len(task.clicked))
        self.assertIn(task.clicked[0], BOSS_POINTS)

    def test_simplified_title_still_works(self):
        task = PageTask([("请选择在核心遇见的首领", 0.484, 0.928, 0.25), ("灵魂收割者", 0.358, 0.706, 0.10)])
        self.assertTrue(utils_sortie.handle_boss_selection(task))
        self.assertEqual(["(0.358, 0.706)"], task.clicked)

    def test_other_page_is_ignored(self):
        self.assertFalse(utils_sortie.handle_boss_selection(PageTask([("請選擇功能。", 0.484, 0.928, 0.25)])))


class TestRestConfirm(unittest.TestCase):

    def test_traditional_and_simplified_confirm(self):
        self.assertTrue(utils._wait_for_rest_confirm(PageTask([], confirm=["確認"])))
        self.assertTrue(utils._wait_for_rest_confirm(PageTask([], confirm=["确认"])))
        task = PageTask([])
        self.assertFalse(utils._wait_for_rest_confirm(task))
        self.assertIn("等待休息确认按钮超时", task.logs)


class TestSortieRest(unittest.TestCase):

    def rest_page(self, *texts):
        return PageTask(SORTIE_REST + list(texts), SORTIE_FEATURES, confirm=["確認"])

    def test_unreadable_hp_waits_for_next_frame(self):
        task = self.rest_page(CREDIT)
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual([], task.clicked)  # 读不到生命值：本帧不做选择
        task.show(SORTIE_REST + [CREDIT, hp(150)])  # 下一帧读到 12%
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual(["rest"], task.clicked)
        self.assertFalse(task.node_status["flash_or_rest"])  # 等到了「確認」，状态已复位

    def test_hp_never_readable_rests(self):
        task = self.rest_page(CREDIT)
        for _ in range(REST_READ_RETRIES):
            self.assertTrue(utils_sortie.handle_rest_sortie(task))
            self.assertEqual([], task.clicked)
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual(["rest"], task.clicked)  # 原来按 100% 处理会闪光

    def test_unreadable_credit_waits_for_next_frame(self):
        task = self.rest_page(hp(1100))
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual([], task.clicked)
        task.show(SORTIE_REST + [CREDIT, hp(1100)])
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual(["闪光"], task.clicked)  # 92% ≥ 60%，信用点够

    def test_readable_values_decide_immediately(self):
        task = self.rest_page(CREDIT, hp(1100))
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual(["闪光"], task.clicked)
        task = self.rest_page(CREDIT, hp(300))
        self.assertTrue(utils_sortie.handle_rest_sortie(task))
        self.assertEqual(["rest"], task.clicked)


class TestChaosRest(unittest.TestCase):

    def rest_page(self, *texts):
        return PageTask(CHAOS_REST + list(texts), CHAOS_FEATURES, confirm=["確認"])

    def test_unreadable_hp_retries_then_rests(self):
        task = self.rest_page(CREDIT)
        for _ in range(REST_READ_RETRIES):
            self.assertTrue(utils.handle_rest(task))
            self.assertEqual([], task.clicked)
        self.assertTrue(utils.handle_rest(task))
        self.assertEqual(["rest"], task.clicked)  # 原来会选冥想

    def test_readable_hp_decides_as_before(self):
        task = self.rest_page(CREDIT, hp(300))
        self.assertTrue(utils.handle_rest(task))
        self.assertEqual(["rest"], task.clicked)  # 25% < 50%
        task = self.rest_page(CREDIT, hp(1100))
        self.assertTrue(utils.handle_rest(task))
        self.assertEqual(["meditate"], task.clicked)


if __name__ == '__main__':
    unittest.main()
