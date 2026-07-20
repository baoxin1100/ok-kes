import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


OK_TASKS_DIR = Path(__file__).resolve().parents[1] / "ok_tasks"
if str(OK_TASKS_DIR) not in sys.path:
    sys.path.insert(0, str(OK_TASKS_DIR))

import utils_sortie
import utils


def make_box(name, x, y, width=100, height=40):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


class FakeTask:
    width = 1920
    height = 1080

    def __init__(self, boxes=None):
        self.all_texts = list(boxes or [])
        self.clicked_boxes = []
        self.clicked_points = []
        self.sent_keys = []
        self.logs = []
        self.scrolls = []
        self.swipes = []
        self.disabled = False
        self.frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def log_debug(self, message):
        self.logs.append(message)

    def log_info(self, message):
        self.logs.append(message)

    def click_box(self, box):
        self.clicked_boxes.append(box)

    def click(self, x, y):
        self.clicked_points.append((x, y))

    def ocr(self, *args, **kwargs):
        region = kwargs.get("box")
        if region is None:
            return self.all_texts
        return [
            box for box in self.all_texts
            if region.x <= box.x + box.width / 2 <= region.x + region.width
            and region.y <= box.y + box.height / 2 <= region.y + region.height
        ]

    def sleep(self, _seconds):
        pass

    def send_key(self, key):
        self.sent_keys.append(key)

    def scroll_relative(self, *args):
        self.scrolls.append(args)

    def swipe_relative(self, *args, **kwargs):
        self.swipes.append((args, kwargs))

    def disable(self):
        self.disabled = True

    def box_of_screen(self, x1, y1, x2, y2):
        return SimpleNamespace(
            x=int(x1 * self.width),
            y=int(y1 * self.height),
            width=int((x2 - x1) * self.width),
            height=int((y2 - y1) * self.height),
        )

    def find_feature(self, **_kwargs):
        return []


class TestSortieMemberSelection(unittest.TestCase):
    def test_candidate_filter_rejects_labels_and_numbers(self):
        hero = make_box("海德玛丽", 325, 738, 128, 47)
        task = FakeTask([
            hero,
            make_box("攻击", 658, 846, 74, 37),
            make_box("50", 756, 383, 84, 78),
            make_box("01", 780, 858, 54, 57),
        ])

        self.assertEqual([hero], utils_sortie._battle_member_boxes(task))

    def test_click_uses_recognized_hero_box(self):
        hero = make_box("海德玛丽", 325, 738, 128, 47)
        task = FakeTask()

        utils_sortie._click_battle_member_row(task, hero)

        self.assertEqual([hero], task.clicked_boxes)
        self.assertIn("x=0.2026", task.logs[-1])

    def test_missing_priority_hero_stops_without_random_click(self):
        task = FakeTask([make_box("米卡", 660, 413, 74, 46)])

        with patch.object(utils_sortie, "_get_battle_member_priority", return_value=["海德玛丽"]):
            result = utils_sortie._select_battle_member(task, max_scrolls=0)

        self.assertTrue(result)
        self.assertTrue(task.disabled)
        self.assertEqual([], task.clicked_boxes)
        self.assertTrue(any("避免随机误选" in message for message in task.logs))

    def test_battle_member_search_drags_inside_left_list_to_scroll_down(self):
        task = FakeTask([make_box("米卡", 660, 413, 74, 46)])

        with patch.object(utils_sortie, "_get_battle_member_priority", return_value=["海德玛丽"]):
            result = utils_sortie._select_battle_member(task, max_scrolls=1)

        self.assertTrue(result)
        self.assertEqual([], task.scrolls)
        self.assertEqual([
            ((0.30, 0.68, 0.30, 0.64), {"duration": 0.8}),
        ], task.swipes)
        self.assertTrue(any("微拖拽" in message for message in task.logs))

    def test_repeated_selection_validation_failure_stops_task(self):
        task = FakeTask()
        selected = make_box("海德玛丽", 600, 700, 128, 47)

        with patch.object(utils_sortie, "_selected_battle_member_match", return_value=False):
            for _ in range(3):
                utils_sortie._confirm_battle_member_selection(task, "海德玛丽", selected)

        self.assertTrue(task.disabled)
        self.assertEqual(3, task._battle_member_validation_failures)

    def test_selection_validates_clicked_region_without_opening_config_then_confirms(self):
        selected = make_box("海德玛丽", 600, 700, 128, 47)
        task = FakeTask([selected])

        with patch.object(utils_sortie, "_selected_battle_member_match", return_value=True), \
                patch.object(utils_sortie, "calculate_dominant_hue", return_value=10):
            result = utils_sortie._confirm_battle_member_selection(task, "海德玛丽", selected)

        self.assertTrue(result)
        self.assertEqual([], task.clicked_boxes)
        self.assertEqual([(0.906, 0.936)], task.clicked_points)
        self.assertEqual(0, task._battle_member_validation_failures)

    def test_clicked_member_region_validation_finds_expected_hero(self):
        selected = make_box("海德玛丽", 600, 700, 128, 47)
        task = FakeTask([make_box("海德玛丽", 605, 702, 128, 47)])

        self.assertTrue(utils_sortie._selected_battle_member_match(task, "海德玛丽", selected))

    def test_clicked_member_region_validation_ignores_same_name_elsewhere(self):
        selected = make_box("海德玛丽", 600, 700, 128, 47)
        task = FakeTask([make_box("海德玛丽", 120, 180, 128, 47)])

        self.assertFalse(utils_sortie._selected_battle_member_match(task, "海德玛丽", selected))

    def test_three_actual_card_attempts_without_hand_change_finish_turn(self):
        task = FakeTask()
        signature = (3, (("剑雨", "1"), ("极光剑", "2")))

        utils_sortie._mark_battle_card_attempt(task, signature)
        self.assertFalse(utils_sortie._resolve_battle_card_attempt(task, signature))
        utils_sortie._mark_battle_card_attempt(task, signature)
        self.assertFalse(utils_sortie._resolve_battle_card_attempt(task, signature))
        utils_sortie._mark_battle_card_attempt(task, signature)
        self.assertTrue(utils_sortie._resolve_battle_card_attempt(task, signature))

    def test_successful_card_attempt_resets_failure_count(self):
        task = FakeTask()
        before = (3, (("剑雨", "1"), ("极光剑", "2")))
        after = (2, (("极光剑", "1"),))
        task._battle_failed_attempts = 1

        utils_sortie._mark_battle_card_attempt(task, before)
        should_finish = utils_sortie._resolve_battle_card_attempt(task, after)

        self.assertFalse(should_finish)
        self.assertEqual(0, task._battle_failed_attempts)

    def test_ocr_card_name_changes_do_not_fake_success_when_hand_count_is_unchanged(self):
        task = FakeTask()
        before = (2, (("护音治疗", "1"),))
        ocr_variants = [
            (2, (("扩音治疗", "1"),)),
            (2, (("护音治行", "2"),)),
            (2, (("护音治疗", "1"),)),
        ]

        for index, current in enumerate(ocr_variants):
            utils_sortie._mark_battle_card_attempt(task, before)
            should_finish = utils_sortie._resolve_battle_card_attempt(task, current)
            self.assertEqual(index == 2, should_finish)
            before = current

        self.assertEqual(3, task._battle_failed_attempts)
        self.assertTrue(any("忽略OCR卡名或按键波动" in message for message in task.logs))

    def test_missing_finish_turn_feature_preserves_pending_attempt(self):
        task = FakeTask()
        signature = (3, (("剑雨", "1"),))
        utils_sortie._mark_battle_card_attempt(task, signature)

        with patch.object(utils_sortie, "_read_hand_count", return_value=3), \
                patch.object(utils_sortie, "is_frame_stuck", return_value=False):
            handled = utils_sortie.handle_battle_page(task)

        self.assertTrue(handled)
        self.assertEqual(signature, task._pending_battle_hand_signature)

    def test_pending_card_attempt_bypasses_stuck_recovery_and_finishes_after_three_failures(self):
        task = FakeTask()
        cards = [{"name": "极光剑", "key": "1", "left_x": 0.5}]
        card_names = [make_box("极光剑", 900, 700)]
        signature = utils_sortie._battle_hand_signature(1, cards, card_names)
        utils_sortie._mark_battle_card_attempt(task, signature)

        with patch.object(utils_sortie, "_read_hand_count", return_value=1), \
                patch.object(utils_sortie, "_hand_card_names", return_value=card_names), \
                patch.object(utils_sortie, "_hand_cards", return_value=cards), \
                patch.object(utils_sortie, "is_frame_stuck", return_value=True) as stuck, \
                patch.object(task, "find_feature", return_value=[object()]):
            self.assertTrue(utils_sortie.handle_battle_page(task))
            self.assertTrue(utils_sortie.handle_battle_page(task))
            self.assertTrue(utils_sortie.handle_battle_page(task))

        self.assertEqual(0, stuck.call_count)
        self.assertEqual("e", task.sent_keys[-1])
        self.assertEqual(0, task._battle_failed_attempts)
        self.assertIsNone(task._pending_battle_hand_signature)

    def test_finish_turn_sends_e_and_resets_tracking(self):
        task = FakeTask()
        task._pending_battle_hand_signature = (3, ())
        task._battle_failed_attempts = 2
        task._last_attempted_card = "剑雨"
        task._play_stuck_count = 1

        result = utils_sortie._finish_battle_turn(task, "无牌可用")

        self.assertTrue(result)
        self.assertEqual(["e"], task.sent_keys)
        self.assertIsNone(task._pending_battle_hand_signature)
        self.assertEqual(0, task._battle_failed_attempts)
        self.assertIsNone(task._last_attempted_card)
        self.assertEqual(0, task._play_stuck_count)

    def test_select_card_does_not_match_single_character_ocr_fragment(self):
        fragment = make_box("雨", 600, 145, 32, 28)
        type_label = make_box("技能", 590, 180, 52, 24)
        task = FakeTask([fragment, type_label])

        selected = utils.select_card(task, ["剑雨"], max_scrolls=0)

        self.assertEqual(0, selected)
        self.assertEqual([], task.clicked_boxes)

    def test_select_card_uses_flash_card_list_order(self):
        sword_rain = make_box("剑雨", 600, 145, 80, 30)
        sword_rain_type = make_box("技能", 610, 180, 60, 24)
        aurora = make_box("展开极光", 900, 145, 120, 30)
        aurora_type = make_box("技能", 930, 180, 60, 24)
        task = FakeTask([sword_rain, sword_rain_type, aurora, aurora_type])

        selected = utils.select_card(
            task,
            ["展开极光", "剑雨"],
            max_scrolls=0,
        )

        self.assertEqual(1, selected)
        self.assertEqual([aurora], task.clicked_boxes)


if __name__ == "__main__":
    unittest.main()
