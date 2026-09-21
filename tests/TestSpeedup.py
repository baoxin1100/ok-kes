# 卡厄思模式加速模式（ok_tasks/speedup.py）：时序、并行匹配、路线页等待、牌库翻页与删卡测试
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

import config_io  # noqa: E402
import speedup  # noqa: E402
import utils  # noqa: E402
import utils_chaos  # noqa: E402
import utils_sortie  # noqa: E402
from utils import _simplify_texts  # noqa: E402

OCR_TIME = 0.13
WIDTH, HEIGHT = 2560, 1440
# 测试中会被加速模式包装或被替身替换的 utils 函数，每个用例结束后还原
PATCHED_UTILS = ("_scroll_card_page", "_recognize_cards_by_features", "select_card", "recognize_cards_in_deck",
                 "_get_card_list", "region_white_ratio", "_get_game_text", "is_button_active")

# 合成画面：把每个并行匹配组里的图标埋在已知位置，供真实 cv2.matchTemplate 匹配
_rng = np.random.default_rng(7)
SCENE = _rng.integers(0, 255, (1300, 2200, 3), dtype=np.uint8)
TEMPLATES = {}
for _index, _name in enumerate(speedup._GROUP_OF):
    _template = _rng.integers(0, 255, (60, 60, 3), dtype=np.uint8)
    TEMPLATES[_name] = _template
    _y, _x = 40 + (_index // 12) * 150, 40 + (_index % 12) * 170
    SCENE[_y:_y + 60, _x:_x + 60] = _template
ROUTE_BASE = _rng.integers(0, 255, (700, 900, 3), dtype=np.uint8)
ROUTE_FINAL = {n: (60 + (i % 3) * 250, 60 + (i // 3) * 200) for i, n in enumerate(speedup._PARALLEL_GROUPS[0])}


class Box:
    def __init__(self, name, x, y, width=160, height=48):
        self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

    def area(self):
        return self.width * self.height


class TaskDisabled(Exception):
    pass


class Frame(np.ndarray):
    """一帧画面：与 ok 框架一样本身是像素数组；boxes 是这帧上的 OCR 文字框。"""


PAGES = {
    "A": [Box("标题", 1100, 150), Box("说明文字", 1000, 600), Box("确认", 1800, 1250)],
    "B": [Box("奖励", 1100, 150), Box("继续进行", 2200, 1300), Box("卡牌", 600, 700)],
    "SHOP": [Box("商店", 1100, 150), Box("免费", 1400, 1300), Box("货币", 2200, 60)],
    "MULTI": [Box("打开", 1200, 700), Box("菜单", 200, 100)],
    "ROUTE": [Box("路线", 300, 100), Box("第3层", 2300, 100)],
    "LONG": [Box("长按卡牌", 1200, 700)],
    "BATTLE": [Box("5/10", 1300, 1390)],
    "MATCH": [Box("匹配测试", 300, 100)],
    "ROUTE_SETTLE": [Box("路线稳定测试", 300, 100)],
    "REMOVE": [Box("请选择1张要移除的卡牌", 300, 60)],
    "EMPTY": [],
}
FADING = [Box("标题", 1100, 150)]  # 过渡中：按钮已消失，只剩残影文字
DECK = ["声音测试", "安可", "聚光灯", "音乐开始", "暗黑之刃", "物质再生", "黑暗斩击", "共鸣之暗",
        "掠食者之刃", "点心时间", "喘气", "安可", "聚光灯", "声音测试", "音乐开始", "黑暗斩击"]  # 4 行


class Game:
    """模拟游戏：点击后延迟 delay 秒开始过渡，duration 秒后切到目标页面；另含可滚动的牌库和可变的画面。"""

    def __init__(self, page, rules=None):
        self.page, self.rules, self.transition, self.clicks = page, rules or {}, None, []
        self.deck, self.deck_offset, self.scrolls, self.deck_views = [], 0, [], 0
        self.deck_anim, self.scroll_times, self.recognize_log, self.seen = None, [], [], []
        self.selected_cards = set()  # 已选中（金色边框）的牌库序号
        self.image_fn = None
        # 战斗出牌：按数字键后 CARD_RAISE 秒卡牌上滑到位，回车后 CARD_PLAY 秒手牌数减少（或弹出选择页面）
        self.hand, self.keys, self.raise_at, self.play_at = 0, [], None, None
        self.play_fails, self.popup_on_enter, self.popup_at = False, False, None

    def on_key(self, key):
        now = time.time()
        self.keys.append((now, key))
        if key.isdigit():
            self.raise_at = now + CARD_RAISE
        elif key == "enter" and self.hand and self.popup_on_enter:
            self.popup_at = self.popup_at or now + CARD_PLAY
        elif key == "enter" and self.hand and not self.play_fails:
            self.play_at = now + CARD_PLAY

    def boxes_at(self, now):
        if self.page == "BATTLE_PLAY":
            if self.popup_at and now >= self.popup_at:
                return [Box("请选择功能", 1150, 180)]  # 弹窗盖住了手牌数
            if self.play_at and now >= self.play_at:
                self.hand -= 1
                self.play_at, self.raise_at = None, None
            return [Box(f"{self.hand}/10", int(0.515 * WIDTH) - 60, int(0.972 * HEIGHT) - 24, 120, 48)]
        if self.transition:
            start, end, target, fading = self.transition
            if now >= end:
                self.page, self.transition = target, None
            elif now >= start:
                return fading
        return PAGES[self.page]

    def image_at(self, now):
        return self.image_fn(now) if self.image_fn else SCENE

    def on_click(self, now):
        self.clicks.append((now, self.page))
        rule = self.rules.get(self.page)
        if rule and self.transition is None:
            delay, duration, target, fading = rule
            self.transition = (now + delay, now + delay + duration, target, fading)

    # 牌库：每行 4 张，一次 3 格滚动移动半行（与实测一致）。视野里有 4 个半行位置：0~2 能正常识别；
    # 3 是最下面一行，描述在识别区域外，只有允许“只凭卡名保留”时才识别得到（与日志实测一致）
    def _rows(self):
        return [self.deck[i:i + 4] for i in range(0, len(self.deck), 4)]

    def _max_offset(self):
        return max(0, 2 * len(self._rows()) - 4)

    def visible_deck(self, include_bottom=False):
        """返回视野里的 (牌库序号, 卡名)。"""
        self.deck_views += 1
        seen, visible = [], []
        for index, row in enumerate(self._rows()):
            slot = 2 * index - self.deck_offset
            if 0 <= slot <= 2 or (slot == 3 and include_bottom):
                seen += [(index, card) for card in row]
                visible += [(index * 4 + i, card) for i, card in enumerate(row)]
        self.seen.append(seen)
        return visible

    def deck_at_bottom(self):
        return self.deck_offset >= self._max_offset()

    def on_scroll(self, count):
        self.scrolls.append(count)
        self.scroll_times.append(time.time())
        if count < 0:
            target = min(self.deck_offset + 1, self._max_offset())
            if target != self.deck_offset:
                self.deck_anim = (time.time(), self.deck_offset, target)
            self.deck_offset = target


class FakeExecutor:
    """与 ok TaskExecutor 中 sleep/next_frame/frame/reset_scene 的时序一致。"""

    def __init__(self, game):
        self.game, self._frame, self.paused, self.current_task = game, None, False, None

    def check_enabled(self):
        if self.current_task is not None and self.current_task.disabled:
            raise TaskDisabled()

    def reset_scene(self, check_enabled=True):
        if check_enabled:
            self.check_enabled()
        self._frame = None

    def next_frame(self, time_out=6):
        self.reset_scene()
        now = time.time()
        self._frame = np.asarray(self.game.image_at(now)).view(Frame)
        self._frame.boxes = list(self.game.boxes_at(now))
        return self._frame

    @property
    def frame(self):
        if self._frame is None:
            self.next_frame()
        return self._frame

    def sleep(self, timeout):
        self.reset_scene(check_enabled=False)
        end = time.time() + timeout
        while True:
            self.check_enabled()
            remaining = end - time.time()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.005))


class FakeChaosTask:
    """点击、睡眠、移动、匹配等方法照抄 ok BaseTask 的调用关系（click_box 默认 after_sleep=1）。"""

    def __init__(self, game, enabled=True):
        self._executor = FakeExecutor(game)
        self.default_config, self.config_description = {}, {}
        self.config = {speedup.ENABLE_KEY: enabled, speedup.HOVER_KEY: 0.1, speedup.INTERVAL_KEY: 0.3,
                       "优先移除基础牌": False, "刷空档": False, "移除卡牌列表": ["粉丝福利", "拍照时间"]}
        self.member_status = {"deck": {}}
        self.trigger_interval = 1
        self.all_texts, self.logs, self.marks, self.match_log = [], [], {}, []
        self.disabled = False
        self.width, self.height = WIDTH, HEIGHT

    @property
    def executor(self):
        return self._executor

    @property
    def frame(self):
        return self.executor.frame

    def sleep(self, timeout):
        self.executor.sleep(timeout)
        return True

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1, move=True,
              down_time=0.02, after_sleep=0, key='left', hcenter=False, vcenter=False):
        if isinstance(x, Box) or isinstance(x, list):
            return self.click_box(x, move_back=move_back, move=move, down_time=down_time, after_sleep=after_sleep)
        elif 0 < x < 1 or 0 < y < 1:
            return self.click_relative(x, y, after_sleep=after_sleep, name=name)
        self.executor.game.on_click(time.time())
        if after_sleep > 0:
            self.sleep(after_sleep)
        self.executor.reset_scene()
        return True

    def click_relative(self, x, y, after_sleep=0, name=None, **kwargs):
        self.click(int(self.width * x), int(self.height * y), name=name, after_sleep=after_sleep)

    def click_box(self, box=None, relative_x=0.5, relative_y=0.5, raise_if_not_found=False,
                  move_back=False, move=True, down_time=0.01, after_sleep=1):
        if isinstance(box, list):
            box = box[0]
        x, y = int(box.x + box.width * relative_x), int(box.y + box.height * relative_y)
        return self.click(x, y, name=box.name, after_sleep=after_sleep)

    def move_relative(self, x, y):
        self.move(int(self.width * x), int(self.height * y))

    def move(self, x, y):
        self.marks["move"] = time.time()
        self.executor.reset_scene()

    def scroll_relative(self, x, y, count):
        self.scroll(int(self.width * x), int(self.height * y), count)

    def scroll(self, x, y, count):
        self.executor.game.on_scroll(count)
        self.executor.reset_scene()

    def is_adb(self):
        return False

    def mouse_down(self, x=-1, y=-1, name=None, key="left"):
        self.marks["down"] = time.time()
        self.executor.reset_scene()

    def mouse_up(self, name=None, key="left"):
        self.marks["up"] = time.time()

    def send_key(self, key, down_time=0.02, interval=-1, after_sleep=0):
        self.executor.game.on_key(str(key))
        self.executor.reset_scene()

    def ocr(self, x=0, y=0, to_x=1, to_y=1, match=None, frame=None, **kwargs):
        """与 ok 框架相同：可以只识别一块区域，也可以指定帧；区域越小越快。"""
        image = frame if frame is not None else self.executor.frame
        whole = (x, y, to_x, to_y) == (0, 0, 1, 1)
        time.sleep(OCR_TIME if whole else OCR_TIME / 4)
        boxes = [Box(b.name, b.x, b.y, b.width, b.height) for b in image.boxes]
        if whole:
            return boxes
        return [b for b in boxes if x <= (b.x + b.width / 2) / self.width <= to_x
                and y <= (b.y + b.height / 2) / self.height <= to_y]

    def find_feature(self, feature_name=None, horizontal_variance=0, vertical_variance=0, threshold=0,
                     box=None, frame=None, limit=0):
        # 与 ok 框架相同：没传 frame 就取 executor.frame；匹配用真实 cv2.matchTemplate
        image = frame if frame is not None else self.executor.frame
        self.match_log.append((feature_name, threading.current_thread().name, id(image), time.time()))
        area = image
        if box is not None:
            area = area[box.y:box.y + box.height, box.x:box.x + box.width]
        result = cv2.matchTemplate(area, TEMPLATES[feature_name], cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= (threshold or 0.8))
        return [Box(feature_name, int(x), int(y), 60, 60) for x, y in zip(xs, ys)]

    def log_info(self, message):
        self.logs.append(message)

    def info_set(self, key, value):
        self.logs.append(f"{key}={value}")

    def _check_upload_if_needed(self):
        pass

    def run(self):
        # 与 ChaosMode.run() 结构一致，供 speedup 的兼容性检查使用
        self.all_texts = _simplify_texts(self.ocr())
        for handle_page in utils_chaos.PAGE_HANDLERS:
            if handle_page(self):
                return
        self._check_upload_if_needed()


def run_executor(task, seconds, stop=None):
    """仿 TaskExecutor.execute：距上次触发超过 trigger_interval 才触发，触发前先取帧。"""
    executor, last, end = task.executor, 0.0, time.time() + seconds
    while time.time() < end and not (stop and stop()):
        now = time.time()
        if now - last > task.trigger_interval:
            last = now
            executor.current_task = task
            try:
                executor.next_frame()
                task.run()
            except TaskDisabled:
                task.marks["stopped"] = time.time()
                task.disabled = False
            executor.current_task = None
        else:
            time.sleep(0.002)


def find(task, name):
    return next((b for b in task.all_texts if b.name == name), None)


def handle_center_confirm(task):
    box = find(task, "确认")
    if box:
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_page_b(task):
    if find(task, "继续进行"):
        task.marks.setdefault("reached_b", time.time())
        return True
    return False


def handle_free(task):
    box = find(task, "免费")
    if box:
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_multi_step(task):
    box = find(task, "打开")
    if box:
        task.click_box(box, after_sleep=0)
        task.marks["click1"] = time.time()
        task.sleep(0.5)
        _ = task.frame
        task.marks["frame_after_sleep"] = time.time()
        task.click(0.5, 0.5)
        task.sleep(1)
        return True
    return False


def handle_route_selection(task):
    if find(task, "路线"):
        task.marks["settle_start"] = time.time()
        task.sleep(1)
        _ = task.frame
        task.marks["settle_end"] = time.time()
        task.move_relative(0.6, 0.5)
        task.sleep(0.5)
        task.click(0.6, 0.5)
        task.marks["route_click"] = time.time()
        task.sleep(2)
        return True
    return False


def handle_long_press(task):
    if find(task, "长按卡牌"):
        task.move_relative(0.5, 0.5)
        task.mouse_down(1280, 720)
        task.sleep(2)
        task.mouse_up()
        task.sleep(1)
        _ = task.frame
        task.marks["frame_after_up"] = time.time()
        return True
    return False


def handle_battle_auto_check(task):
    return bool(find(task, "5/10"))


MATCH_BOX = Box("区域", 0, 0, 2200, 1300)


def handle_matching(task):
    """按 ok-kes 的写法依次匹配：牌库/选卡页卡牌类型、路线页 9 种、小地图两组（阈值不同）。"""
    if not find(task, "匹配测试"):
        return False
    task.marks["sleep_call"] = time.time()
    task.sleep(1)
    cards = {n: task.find_feature(feature_name=n, box=MATCH_BOX, threshold=0.65)
             for n in speedup._PARALLEL_GROUPS[3] + speedup._PARALLEL_GROUPS[4]}
    route = {n: task.find_feature(feature_name=n, box=MATCH_BOX) for n in speedup._PARALLEL_GROUPS[0]}
    task.marks["route_end"] = time.time()
    minimap = {n: task.find_feature(feature_name=n, box=MATCH_BOX, threshold=0.85)
               for n in speedup._PARALLEL_GROUPS[1]}
    minimap.update({n: task.find_feature(feature_name=n, box=MATCH_BOX, threshold=0.65)
                    for n in speedup._PARALLEL_GROUPS[2]})
    task.find_feature(feature_name="safezone", box=MATCH_BOX, limit=1)  # 带额外参数：应走原逻辑
    task.marks["results"] = {k: [(b.x, b.y) for b in v] for k, v in {**cards, **route, **minimap}.items()}
    return True


def route_image_fn(anim_end, icons=True):
    """anim_end 之前路线图标横向来回移动，之后停在最终位置；icons=False 模拟没有普通节点图标的 Boss 节点。"""
    def image_at(now):
        image = ROUTE_BASE.copy()
        if icons:
            shift = int(((anim_end - now) * 400) % 200) if now < anim_end else 0
            for name, (x, y) in ROUTE_FINAL.items():
                image[y:y + 60, x + shift:x + shift + 60] = TEMPLATES[name]
        return image
    return image_at


def handle_route_settle(task):
    """仿 handle_route_selection：先 sleep(1) 等图标入场，再逐个匹配 9 种节点/标记。"""
    if not find(task, "路线稳定测试"):
        return False
    task.marks["settle_call"] = time.time()
    task.sleep(1)
    results = {n: task.find_feature(feature_name=n, box=None) for n in speedup._PARALLEL_GROUPS[0]}
    task.marks["settle_done"] = time.time()
    task.marks["positions"] = {n: sorted((b.x, b.y) for b in v) for n, v in results.items()}
    return True


# ---------------- 删卡流程替身：外部行为与 utils 中同名函数一致，内部经 utils.xxx 调用以经过加速包装 ----------------
class SkipButton:
    name, x, y, width, height = "跳过", 2300, 1350, 120, 48


def fake_scroll_card_page(task, x, y, amount, page, distance=0.25):
    task.move_relative(x, y)
    task.sleep(0.05)
    task.scroll_relative(x, y, amount)
    task.sleep(0.5)


def fake_recognize_cards_by_features(task, region, page, feature_types, min_feature_distance, name_offsets,
                                     type_offsets, description_offsets, name_only_feature_thresholds=None,
                                     allow_empty_type_threshold=None):
    """最下面一行只有非咒术图标也允许“只凭卡名保留”时才识别得到；已选中的卡带金色边框。"""
    _ = task.frame
    game = task.executor.game
    name_only = sorted(name_only_feature_thresholds or {})
    game.recognize_log.append((page, name_only, time.time()))
    include_bottom = all(n in name_only for n in ("attack_in_deck", "skill_in_deck", "enhance_in_deck"))
    return [{"name": name, "index": index, "selected": index in game.selected_cards}
            for index, name in game.visible_deck(include_bottom)]


def fake_recognize_cards_in_deck(task, region=(0.274, 0.108, 0.929, 0.874), page=""):
    """与真实实现的调用方式相同：原本只给咒术图标设了“只凭卡名保留”的阈值。"""
    return utils._recognize_cards_by_features(
        task=task, region=region, page=page,
        feature_types={"attack_in_deck": "攻击/基础攻击", "skill_in_deck": "技能/基础技能", "enhance_in_deck": "强化",
                       "hex_in_deck": "咒术", "hex_in_deck_tw": "诅咒"},
        min_feature_distance=0.138, name_offsets=(0, 0, 0, 0), type_offsets=(0, 0, 0, 0),
        description_offsets=(0, 0, 0, 0),
        name_only_feature_thresholds={"hex_in_deck": 0.90, "hex_in_deck_tw": 0.90},
        allow_empty_type_threshold=0.90,
    )


def fake_select_card(task, card_names, count=1, action=""):
    """逐页找目标（跳过已选中的卡）→ 到底后删最底页咒术卡 → 仍不够就点“跳过”。"""
    page = f"select_card-{action}"
    selected = 0

    def pick(card):
        nonlocal selected
        task.click(0.5, 0.5)
        task.executor.game.selected_cards.add(card["index"])
        card["selected"] = True
        selected += 1

    cards = utils.recognize_cards_in_deck(task, page=page)
    while True:
        for card in cards:
            if (selected < count and not card["selected"]
                    and any(t in card["name"] or card["name"] in t for t in card_names)):
                pick(card)
        if selected >= count:
            return True
        if task.executor.game.deck_at_bottom():
            break
        utils._scroll_card_page(task, 0.251, 0.735, -3, page)
        cards = utils.recognize_cards_in_deck(task, page=page)
    if action == "移除":
        for card in cards:
            if selected < count and not card["selected"] and card["name"].startswith("咒术"):
                pick(card)
        if selected >= count:
            return True
    task.click_box(SkipButton())
    return True


def fake_get_card_list(task, key):
    value = task.config.get(key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def handle_remove_page(task):
    """仿 handle_select_card：每次进入删卡页，牌库从顶部开始显示。"""
    if not find(task, "请选择1张要移除的卡牌"):
        return False
    game = task.executor.game
    game.deck_offset, views, scrolls = 0, game.deck_views, len(game.scrolls)
    utils.select_card(task, utils._get_card_list(task, "移除卡牌列表"), count=1, action="移除")
    task.marks.setdefault("flows", []).append((game.deck_views - views, len(game.scrolls) - scrolls))
    return True


DECK_ANIM = 0.2
DECK_TEXTURE = _rng.integers(0, 255, (3000, 2200, 3), dtype=np.uint8)


def deck_image_fn(game):
    """卡牌区域画面随滚动移动：每次滚动后有 0.2 秒动画，然后静止。"""
    y1, y2, x1, x2 = int(0.108 * 1300), int(0.874 * 1300), int(0.274 * 2200), int(0.929 * 2200)

    def image_at(now):
        visual = game.deck_offset
        if game.deck_anim:
            start, before, after = game.deck_anim
            visual = before + (after - before) * min(1.0, (now - start) / DECK_ANIM)
        image = SCENE.copy()
        shift = int(visual * 150)
        image[y1:y2, x1:x2] = DECK_TEXTURE[shift:shift + (y2 - y1), x1:x2]
        return image
    return image_at


def views_per_row(game):
    return [sum(1 for page in game.seen if any(row == index for row, _ in page)) for index in range(4)]


def waits_after_scroll(game):
    """每次滚动到下一次识别卡牌的间隔。"""
    times = [t for _, _, t in game.recognize_log]
    return [next(t - s for t in times if t > s) for s in game.scroll_times if any(t > s for t in times)]


# ---------------- 删卡目标不够：直接调用真实的 handle_select_card / select_card / handle_remove ----------------
BLACK = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)


def screen_box(name, rx, ry, width=200, height=40):
    """中心在相对坐标 (rx, ry) 的文字框。"""
    return Box(name, int(rx * WIDTH - width / 2), int(ry * HEIGHT - height / 2), width, height)


def deck_cards(targets):
    """一页牌库：目标卡在前，后面跟两张非目标卡。"""
    return [{"name": name, "type": "技能", "description": "", "x": 0.35 + 0.15 * i, "y": 0.3,
             "selected": False, "feature_name": "skill_in_deck"}
            for i, name in enumerate(targets + ["声音测试", "安可"])]


class SelectCardPageTask:
    """真实删卡流程用到的任务接口；卡牌识别、滚动条、按钮颜色这类读屏幕的函数由 use_real_removal_flow 替换。"""
    name = "测试"  # 不走“滚到目标主战员”那一步

    def __init__(self, enabled, title, targets):
        self.default_config, self.config_description = {}, {}
        self.config = {speedup.ENABLE_KEY: enabled, "优先移除基础牌": False, "刷空档": False,
                       "移除卡牌列表": ["拍照时间", "粉丝福利"], "复制卡牌列表": ["拍照时间", "粉丝福利"]}
        self.width, self.height, self.trigger_interval = WIDTH, HEIGHT, 1
        self.executor = SimpleNamespace(paused=False, current_task=None, reset_scene=lambda check_enabled=True: None)
        self.node_status, self.picked, self.clicked, self.logs = {}, set(), [], []
        self.deck = deck_cards(targets)
        self.show_title(title)

    def show_title(self, title):
        self.all_texts = [screen_box(title, 0.198, 0.039)]

    @property
    def frame(self):
        return BLACK

    def sleep(self, timeout):
        return True

    def click(self, x=-1, y=-1, name=None, **kwargs):
        self.clicked.append(name or "卡牌")
        self.picked.update(c["name"] for c in self.deck if name is None and (c["x"], c["y"]) == (x, y))
        return True

    def click_box(self, box=None, relative_x=0.5, relative_y=0.5, **kwargs):
        return self.click(box.x + box.width / 2, box.y + box.height / 2, name=box.name)

    def move(self, *args, **kwargs):
        pass

    def move_relative(self, x, y):
        self.move(x, y)

    scroll = mouse_down = mouse_up = send_key = move

    def run(self):
        pass

    def find_feature(self, **kwargs):
        return []

    def feature_exists(self, name):
        return False

    def is_adb(self):
        return False

    def log_info(self, message):
        self.logs.append(message)

    def ocr(self):
        return [screen_box("跳过", 0.80, 0.94), screen_box("移除", 0.945, 0.918, 120)]

    def box_of_screen(self, x, y, to_x=1.0, to_y=1.0, **kwargs):
        return screen_box("", (x + to_x) / 2, (y + to_y) / 2, int((to_x - x) * WIDTH), int((to_y - y) * HEIGHT))


# ---------------- 出击模式：run() 用 utils_sortie 的处理函数列表；战斗出牌替身 ----------------
CARD_RAISE = 0.10  # 按数字键后卡牌上滑到位所需时间（实测 0.01~0.04 秒）
CARD_PLAY = 0.25   # 回车后手牌数减少所需时间（实测 0.2~0.3 秒）
PAGES["BATTLE_PLAY"] = []  # 内容由 Game.boxes_at 按手牌数生成


class FakeSortieTask(FakeChaosTask):
    """出击模式：run() 结构与卡厄思相同，但用的是 utils_sortie 的处理函数列表。"""
    name = "自动出击模式"

    def run(self):
        self.all_texts = _simplify_texts(self.ocr())
        for handle_page in utils_sortie.PAGE_HANDLERS:
            if handle_page(self):
                return
        self._check_upload_if_needed()


class OtherRunTask(FakeChaosTask):
    """run() 结构与预期不符的任务（例如作者改版后）。"""
    name = "其他任务"

    def run(self):
        self.all_texts = _simplify_texts(self.ocr())
        handle_center_confirm(self)


def battle_image_fn(game):
    """卡牌上滑到位后手牌区域变样，其余时间不动。"""
    y1, y2, x1, x2 = int(0.660 * 1300), int(0.950 * 1300), int(0.159 * 2200), int(0.836 * 2200)

    def image_at(now):
        if not (game.raise_at and now >= game.raise_at):
            return SCENE
        image = SCENE.copy()
        image[y1:y2, x1:x2] = DECK_TEXTURE[:y2 - y1, x1:x2]
        return image
    return image_at


def handle_battle_page(task):
    """替身：与 utils_sortie.handle_battle_page 相同的出牌时序（按数字键 → 等 1 秒 → 回车 → 等 2 秒）。"""
    if not any("/10" in b.name for b in task.all_texts):
        return False
    task.marks.setdefault("plays", []).append(time.time())
    task.send_key("4")
    task.sleep(1)
    task.send_key("enter")
    task.sleep(2)
    return True


def fake_try_all_card_keys(task, count):
    """替身：与 utils_sortie._try_all_card_keys 相同，从手牌数倒着按一遍，每张牌 0.5 + 1 秒。"""
    for index in range(min(count, 9), 0, -1):
        task.send_key(str(index))
        task.sleep(0.5)
        task.send_key("enter")
        task.sleep(1)


def handle_battle_fallback(task):
    """仿 handle_battle_page 未命中出牌优先级时：经 utils_sortie 调用兜底出牌（与真实代码一样走模块属性）。"""
    if not any("/10" in b.name for b in task.all_texts):
        return False
    task.marks.setdefault("plays", []).append(time.time())
    utils_sortie._try_all_card_keys(task, 5)
    return True


class TestSpeedup(unittest.TestCase):

    def setUp(self):
        self._handlers = list(utils_chaos.PAGE_HANDLERS)
        self._is_frame_stuck = utils.is_frame_stuck
        self._ui_only_keys = set(config_io.UI_ONLY_CONFIG_KEYS)
        self._utils = {name: getattr(utils, name) for name in PATCHED_UTILS}
        self._sortie_handlers = list(utils_sortie.PAGE_HANDLERS)
        self._sortie = {name: getattr(utils_sortie, name) for name in ("handle_battle_page", "_try_all_card_keys")}

    def tearDown(self):
        utils_chaos.PAGE_HANDLERS[:] = self._handlers
        utils_sortie.PAGE_HANDLERS[:] = self._sortie_handlers
        for name, function in self._sortie.items():
            setattr(utils_sortie, name, function)
        utils.is_frame_stuck = self._is_frame_stuck
        config_io.UI_ONLY_CONFIG_KEYS.clear()
        config_io.UI_ONLY_CONFIG_KEYS.update(self._ui_only_keys)
        for name, function in self._utils.items():
            setattr(utils, name, function)

    def make(self, page, rules, handlers, enabled=True):
        game = Game(page, rules)
        task = FakeChaosTask(game, enabled)
        speedup.install(task)
        utils_chaos.PAGE_HANDLERS[:] = handlers
        return game, task

    def use_fake_card_helpers(self):
        utils._scroll_card_page = fake_scroll_card_page
        utils._recognize_cards_by_features = fake_recognize_cards_by_features
        utils.select_card = fake_select_card
        utils.recognize_cards_in_deck = fake_recognize_cards_in_deck
        utils._get_card_list = fake_get_card_list
        speedup._patch_deck_scan()
        speedup._patch_partial_removal()

    def use_real_removal_flow(self):
        """删卡流程用真实代码，只替换读屏幕的函数：一页牌库、选中的卡带金色边框、至少选中 1 张时“移除”可点。"""
        utils.recognize_cards_in_deck = lambda task, region=None, page="": [
            dict(card, selected=card["name"] in task.picked) for card in task.deck]
        utils.region_white_ratio = lambda task, region: 0.0
        utils._get_game_text = lambda task, text: text
        utils.is_button_active = lambda task, box: bool(task.picked)

    def select_page(self, title, targets, enabled=True):
        task = SelectCardPageTask(enabled, title, targets)
        speedup.install(task)
        task._speedup["active"] = enabled  # 模拟处于运行中
        return task

    def confirm_removal(self, task):
        """下一轮：右下角“移除”按钮交给真实的 handle_remove。"""
        task.all_texts = [screen_box("移除", 0.945, 0.918, 120)]
        return utils.handle_remove(task)

    # ---------------- 点击后等待 ----------------
    def transition_latency(self, enabled):
        game, task = self.make("A", {"A": (0.1, 0.5, "B", FADING)}, [handle_center_confirm, handle_page_b], enabled)
        run_executor(task, 4, stop=lambda: "reached_b" in task.marks)
        confirm_clicks = sum(1 for _, page in game.clicks if page == "A")
        return task.marks["reached_b"] - game.clicks[0][0], confirm_clicks

    def test_disabled_keeps_original_timing(self):
        latency, clicks = self.transition_latency(enabled=False)
        self.assertGreaterEqual(latency, 2.0)
        self.assertEqual(1, clicks)

    def test_enabled_continues_after_page_responds_without_double_click(self):
        latency, clicks = self.transition_latency(enabled=True)
        self.assertLess(latency, 1.3)
        self.assertEqual(1, clicks)

    def test_unresponsive_page_is_retried_at_original_interval(self):
        game, task = self.make("SHOP", {}, [handle_free])
        run_executor(task, 5.2)
        times = [t for t, _ in game.clicks]
        self.assertGreaterEqual(len(times), 2)
        self.assertGreaterEqual(min(b - a for a, b in zip(times, times[1:])), 2.0)

    def test_multi_step_handler_keeps_intermediate_and_tail_waits(self):
        game, task = self.make("MULTI", {}, [handle_multi_step])
        run_executor(task, 2.5, stop=lambda: len(game.clicks) >= 3)
        self.assertGreaterEqual(task.marks["frame_after_sleep"] - task.marks["click1"], 0.5)
        self.assertGreaterEqual(game.clicks[2][0] - game.clicks[1][0], 1.0)

    def test_settle_wait_kept_and_hover_shortened(self):
        game, task = self.make("ROUTE", {"ROUTE": (0.05, 0.3, "EMPTY", [])}, [handle_route_selection])
        run_executor(task, 3, stop=lambda: "route_click" in task.marks)
        self.assertGreaterEqual(task.marks["settle_end"] - task.marks["settle_start"], 1.0)
        hover = task.marks["route_click"] - task.marks["move"]
        self.assertGreaterEqual(hover, 0.09)
        self.assertLess(hover, 0.3)

    def test_long_press_duration_kept(self):
        game, task = self.make("LONG", {}, [handle_long_press])
        run_executor(task, 3.6, stop=lambda: "frame_after_up" in task.marks)
        self.assertGreaterEqual(task.marks["up"] - task.marks["down"], 2.0)
        self.assertGreaterEqual(task.marks["frame_after_up"] - task.marks["up"], 1.0)

    def test_trigger_interval_in_battle_and_navigation(self):
        game, task = self.make("BATTLE", {}, [handle_battle_auto_check])
        run_executor(task, 0.5)
        self.assertEqual(1.0, task.trigger_interval)
        utils_chaos.PAGE_HANDLERS[:] = [handle_page_b, handle_battle_auto_check]
        game.page = "B"
        run_executor(task, 1.2)
        self.assertEqual(0.3, task.trigger_interval)

    def test_stop_during_wait_resets_state(self):
        game, task = self.make("A", {"A": (5, 1, "B", FADING)}, [handle_center_confirm, handle_page_b])
        timer = threading.Timer(0.6, lambda: setattr(task, "disabled", True))
        timer.start()
        run_executor(task, 1.5)
        timer.join()
        self.assertIn("stopped", task.marks)
        self.assertEqual(0.0, task._speedup["owed_until"])
        self.assertFalse(task._speedup["in_run"])

    def test_stuck_detection_still_samples_about_once_per_second(self):
        calls = []

        def counting_is_frame_stuck(task, stuck_threshold_seconds=30, change_threshold=0.08):
            calls.append(time.time())
            task._last_change_time = time.time()
            return False

        utils.is_frame_stuck = counting_is_frame_stuck
        speedup._keep_stuck_detection_at_one_second()
        task = SimpleNamespace()
        end = time.time() + 2.05
        while time.time() < end:
            utils.is_frame_stuck(task, stuck_threshold_seconds=10)
            time.sleep(0.1)
        self.assertLessEqual(len(calls), 4)
        self.assertGreaterEqual(len(calls), 2)

    def test_speed_options_excluded_from_exported_config(self):
        self.make("EMPTY", {}, [])
        for key in (speedup.ENABLE_KEY, speedup.HOVER_KEY, speedup.INTERVAL_KEY):
            self.assertIn(key, config_io.UI_ONLY_CONFIG_KEYS)

    # ---------------- 并行模板匹配 ----------------
    def matching_run(self, enabled):
        game, task = self.make("MATCH", {}, [handle_matching], enabled)
        run_executor(task, 4, stop=lambda: "results" in task.marks)
        return task

    def test_parallel_matching_matches_sequential_results(self):
        sequential, parallel = self.matching_run(False), self.matching_run(True)
        self.assertEqual(sequential.marks["results"], parallel.marks["results"])
        self.assertEqual(29, sum(1 for boxes in parallel.marks["results"].values() if boxes))
        workers = [c for c in parallel.match_log if c[1].startswith("speedup-match")]
        on_caller = [c for c in parallel.match_log if not c[1].startswith("speedup-match")]
        self.assertEqual(29, len(workers))   # 每个图标只算一次
        self.assertEqual(1, len(on_caller))  # 带 limit 参数的调用走原逻辑
        self.assertEqual(1, len({c[2] for c in parallel.match_log}))  # 同一帧
        self.assertGreaterEqual(min(c[3] for c in parallel.match_log) - parallel.marks["sleep_call"], 1.0)
        self.assertTrue(all(not c[1].startswith("speedup-match") for c in sequential.match_log))

    # ---------------- 路线页识别前的等待 ----------------
    def route_wait(self, anim_seconds, enabled=True, icons=True):
        game, task = self.make("ROUTE_SETTLE", {}, [handle_route_settle], enabled)
        game.image_fn = route_image_fn(time.time() + anim_seconds, icons)
        run_executor(task, 3, stop=lambda: "positions" in task.marks)
        final = {n: [p] for n, p in ROUTE_FINAL.items()}
        return task.marks["settle_done"] - task.marks["settle_call"], task.marks["positions"] == final

    def test_route_icons_settled_early_continue_before_one_second(self):
        wait, at_final_position = self.route_wait(0.2)
        self.assertGreaterEqual(wait, 0.4)
        self.assertLess(wait, 0.85)
        self.assertTrue(at_final_position)

    def test_route_icons_still_moving_wait_full_second(self):
        wait, _ = self.route_wait(2.0)
        self.assertGreaterEqual(wait, 0.95)

    def test_route_boss_node_without_icons_waits_full_second(self):
        wait, _ = self.route_wait(0.0, icons=False)
        self.assertGreaterEqual(wait, 0.95)

    def test_route_disabled_keeps_fixed_wait(self):
        wait, at_final_position = self.route_wait(0.2, enabled=False)
        self.assertGreaterEqual(wait, 0.95)
        self.assertTrue(at_final_position)

    # ---------------- 牌库翻页 ----------------
    def removal_scan(self, enabled, deck=DECK):
        """需删 1 张的删卡页走一遍：逐页找“移除卡牌列表”里的卡，找不到就翻到底。"""
        self.use_fake_card_helpers()
        game, task = self.make("REMOVE", {}, [handle_remove_page], enabled)
        game.deck = list(deck)
        game.image_fn = deck_image_fn(game)
        run_executor(task, 20, stop=lambda: len(task.marks.get("flows", [])) >= 1)
        return game, task

    def test_deck_paging_keeps_steps_reads_bottom_row_and_waits_until_still(self):
        original_game, original = self.removal_scan(False)
        game, task = self.removal_scan(True)
        self.assertEqual((5, 4), original.marks["flows"][0])  # 每次半行：识别 5 页，滚动 4 次
        self.assertEqual(original.marks["flows"], task.marks["flows"])
        self.assertEqual(original_game.scrolls, game.scrolls)
        original_views, views = views_per_row(original_game), views_per_row(game)
        self.assertEqual([1, 3, 3, 1], original_views)
        self.assertTrue(all(v >= o for o, v in zip(original_views, views)), views)
        self.assertGreater(sum(views), sum(original_views))  # 最下面一行也识别到了
        self.assertGreaterEqual(min(waits_after_scroll(original_game)), 0.5)
        self.assertLess(max(waits_after_scroll(game)), 0.45)  # 列表停稳就识别

    def test_deck_scroll_without_movement_waits_full_half_second(self):
        self.use_fake_card_helpers()
        game, task = self.make("REMOVE", {}, [], True)
        game.deck = list(DECK)  # 画面不变：检测不到滚动（例如已经到底）
        task._speedup["active"] = True  # 模拟处于运行中
        task.executor.current_task = task
        speedup._wrap_executor_next_frame(task.executor)
        start = time.time()
        utils._scroll_card_page(task, 0.251, 0.735, -3, "select_card-移除")
        _ = task.frame
        self.assertGreaterEqual(time.time() - start, 0.5)

    def test_name_only_recognition_only_on_remove_and_copy_pages(self):
        self.use_fake_card_helpers()
        game, task = self.make("REMOVE", {}, [], True)
        game.deck = list(DECK)

        def name_only(page, active=True):
            task._speedup["active"] = active
            utils.recognize_cards_in_deck(task, page=page)
            return game.recognize_log[-1][1]

        hex_only = ["hex_in_deck", "hex_in_deck_tw"]
        self.assertIn("attack_in_deck", name_only("select_card-移除"))
        self.assertIn("attack_in_deck", name_only("select_card-复制"))
        self.assertEqual(hex_only, name_only("select_card-闪光"))
        self.assertEqual(hex_only, name_only("select_card-移除", active=False))

    def test_target_in_any_row_is_found(self):
        for row in range(4):
            deck = list(DECK)
            deck[row * 4 + 2] = "拍照时间"
            game, _ = self.removal_scan(True, deck)
            self.assertIn(row * 4 + 2, game.selected_cards, f"第 {row + 1} 行")

    # ---------------- 要求移除多张但目标卡不够（真实删卡流程） ----------------
    def test_partial_targets_removed_instead_of_skipped(self):
        self.use_real_removal_flow()
        task = self.select_page("请选择2张要移除的卡牌", ["拍照时间"])
        self.assertTrue(utils.handle_select_card(task))
        self.assertEqual(["卡牌"], task.clicked)  # 选中目标卡，没有点“跳过”
        self.assertEqual(1, task._pending_removed_card_count)
        self.assertTrue(self.confirm_removal(task))
        self.assertEqual(["卡牌", "移除"], task.clicked)
        self.assertEqual(1, task.node_status["removed_card_count"])

    def test_removed_count_matches_selected_targets(self):
        self.use_real_removal_flow()
        task = self.select_page("请选择3张要移除的卡牌", ["拍照时间", "粉丝福利"])
        utils.handle_select_card(task)
        self.assertNotIn("跳过", task.clicked)
        self.assertTrue(self.confirm_removal(task))
        self.assertEqual(2, task.node_status["removed_card_count"])

    def test_no_target_or_disabled_skips_as_before(self):
        self.use_real_removal_flow()
        task = self.select_page("请选择2张要移除的卡牌", [])
        utils.handle_select_card(task)
        self.assertEqual(["跳过"], task.clicked)
        disabled = self.select_page("请选择2张要移除的卡牌", ["拍照时间"], enabled=False)
        utils.handle_select_card(disabled)
        self.assertEqual(["卡牌", "跳过"], disabled.clicked)
        self.assertEqual(0, disabled._pending_removed_card_count)

    def test_copy_flow_unchanged(self):
        self.use_real_removal_flow()
        task = self.select_page("请选择2张要复制的卡牌", ["拍照时间"])
        utils.handle_select_card(task)
        self.assertEqual(["卡牌", "跳过"], task.clicked)

    def test_skip_on_second_try_when_remove_button_stays_inactive(self):
        self.use_real_removal_flow()
        utils.is_button_active = lambda task, box: False  # 游戏要求选够张数才能确认
        task = self.select_page("请选择2张要移除的卡牌", ["拍照时间"])
        utils.handle_select_card(task)
        self.assertFalse(self.confirm_removal(task))
        task.show_title("请选择2张要移除的卡牌")  # 仍停在选卡页
        utils.handle_select_card(task)
        self.assertEqual(["卡牌", "跳过"], task.clicked)  # 只多进一次选卡
        self.assertEqual(0, task._pending_removed_card_count)

    def test_next_removal_after_confirm_keeps_partial_selection_again(self):
        self.use_real_removal_flow()
        task = self.select_page("请选择2张要移除的卡牌", ["拍照时间"])
        utils.handle_select_card(task)
        self.assertTrue(self.confirm_removal(task))
        task.deck, task.picked = deck_cards(["粉丝福利"]), set()  # 紧接着又一次删卡
        task.show_title("请选择2张要移除的卡牌")
        utils.handle_select_card(task)
        self.assertNotIn("跳过", task.clicked)
        self.assertTrue(self.confirm_removal(task))
        self.assertEqual(2, task.node_status["removed_card_count"])

    # ---------------- 出击模式 ----------------
    def make_sortie(self, page, rules, handlers, enabled=True):
        """与真实情况一致：出击模式的处理函数列表先建好（存的是原函数对象），再装加速模式。"""
        game = Game(page, rules)
        task = FakeSortieTask(game, enabled)
        utils_chaos.PAGE_HANDLERS[:] = []  # 卡厄思的列表留空：出击模式必须用自己的
        utils_sortie.PAGE_HANDLERS[:] = handlers
        speedup.install(task)
        return game, task

    def play_card(self, enabled, raise_card=True, play_works=True, popup=False, handler=None):
        # 出牌函数换成时序相同、尚未包装的替身，装加速模式时会被包装并替换进处理函数列表
        utils_sortie.handle_battle_page = handle_battle_page
        utils_sortie._try_all_card_keys = fake_try_all_card_keys
        game, task = self.make_sortie("BATTLE_PLAY", {}, [handler or handle_battle_page], enabled)
        game.hand, game.play_fails, game.popup_on_enter = 5, not play_works, popup
        game.image_fn = battle_image_fn(game) if raise_card else (lambda now: SCENE)
        run_executor(task, 12, stop=lambda: len(task.marks.get("plays", [])) >= 1)
        return time.time() - game.keys[0][0], game, task

    def test_sortie_uses_its_own_page_handlers(self):
        game, task = self.make_sortie("A", {"A": (0.1, 0.5, "B", FADING)}, [handle_center_confirm, handle_page_b])
        run_executor(task, 4, stop=lambda: "reached_b" in task.marks)
        self.assertIs(utils_sortie, task._speedup["handlers"])
        self.assertLess(task.marks["reached_b"] - game.clicks[0][0], 1.3)
        self.assertEqual(1, sum(1 for _, page in game.clicks if page == "A"))

    def test_incompatible_run_disables_gate_only(self):
        game = Game("A", {"A": (0.1, 0.5, "B", FADING)})
        task = OtherRunTask(game, True)
        speedup.install(task)
        run_executor(task, 3.5)
        self.assertFalse(task._speedup["gate_ok"])
        self.assertEqual(1, len(game.clicks))
        self.assertEqual(0.3, task.trigger_interval)  # 检测间隔优化照常

    def test_page_handler_list_entry_is_replaced(self):
        utils_sortie.handle_battle_page = handle_battle_page
        self.make_sortie("BATTLE_PLAY", {}, [handle_battle_page])
        entry = utils_sortie.PAGE_HANDLERS[0]
        self.assertIsNot(handle_battle_page, entry)  # 列表里存的原函数也换成了包装后的
        self.assertTrue(getattr(entry, "_speedup_wrapped", False))
        self.assertEqual("handle_battle_page", entry.__name__)

    def test_card_play_waits_for_raise_and_hand_count(self):
        original, _, _ = self.play_card(False)
        fast, game, task = self.play_card(True)
        digit = next(t for t, key in game.keys if key.isdigit())
        enter = next(t for t, key in game.keys if key == "enter")
        self.assertGreaterEqual(original, 2.9)
        self.assertLess(fast, 1.2)
        self.assertGreaterEqual(enter - digit, CARD_RAISE)  # 卡牌上滑到位后才回车
        self.assertEqual(4, game.hand)
        self.assertEqual(1.0, task.trigger_interval)  # 仍在战斗中：检测间隔保持 1 秒

    def test_card_play_without_response_waits_original_time(self):
        elapsed, game, _ = self.play_card(True, raise_card=False, play_works=False)
        self.assertGreaterEqual(elapsed, 2.9)
        self.assertEqual(5, game.hand)

    def test_popup_after_card_play_is_handled_soon(self):
        elapsed, game, task = self.play_card(True, popup=True)
        self.assertLess(elapsed, 1.2)
        self.assertEqual(["4", "enter"], [key for _, key in game.keys])
        self.assertEqual(0.3, task.trigger_interval)  # 下一轮按非战斗间隔尽快来处理弹窗

    def test_fallback_card_keys_speed_up_and_stop_on_popup(self):
        original, _, _ = self.play_card(False, handler=handle_battle_fallback)
        fast, game, _ = self.play_card(True, handler=handle_battle_fallback)
        self.assertLess(fast, original / 2)
        self.assertEqual(0, game.hand)
        elapsed, game, _ = self.play_card(True, popup=True, handler=handle_battle_fallback)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(["5", "enter"], [key for _, key in game.keys])  # 弹窗后不再按 4、3、2、1

    def test_real_sortie_mode_run_matches_gated_run(self):
        import SortieMode
        from src.config import config

        task = SortieMode.SortieMode(executor=SimpleNamespace(scene=None, config=config), app=None)
        self.assertTrue(task._speedup["gate_ok"], "SortieMode.run() 已改动，请同步 speedup._gated_run")
        self.assertIs(utils_sortie, task._speedup["handlers"])
        self.assertFalse(task.default_config[speedup.ENABLE_KEY])
        entry = next(h for h in utils_sortie.PAGE_HANDLERS if h.__name__ == "handle_battle_page")
        self.assertTrue(getattr(entry, "_speedup_wrapped", False))
        self.assertIn("handle_battle_page", speedup._BATTLE_HANDLERS)

    # ---------------- 与真实 ChaosMode 的兼容性 ----------------
    def test_real_chaos_mode_run_matches_gated_run(self):
        import ChaosMode
        from src.config import config

        task = ChaosMode.ChaosMode(executor=SimpleNamespace(scene=None, config=config), app=None)
        self.assertTrue(task._speedup["gate_ok"], "ChaosMode.run() 已改动，请同步 speedup._gated_run")
        self.assertFalse(task.default_config[speedup.ENABLE_KEY])


if __name__ == '__main__':
    unittest.main()
