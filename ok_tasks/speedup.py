"""
卡厄思模式、出击模式的加速模式（实验性，默认关闭）。

原逻辑每次点击后按固定时长等待（click_box 自带 1 秒，处理函数再 sleep 0.5~2 秒），
_move_and_click 点击前还固定悬停 0.5 秒，而界面通常不到 1 秒就切换完成。

开启后：
1. 延迟支付等待：处理函数里的 sleep 先记账不真睡，之后它若还要看画面或再操作，
   先把欠的时间补足，保持原有语义；处理函数结束时还欠着的等待交给第 2 步。
2. 文字闸门：只做了一次点击的帧，下一轮 OCR 后先判断页面是否已响应——
   被点的文字还在原处就继续等；页面文字变了，再多识别一次确认不再变化才交给处理函数。
   无论如何不会晚于原逻辑的等待时长。游戏背景一直有动画，所以只看文字，不看像素。
3. 点击前悬停 0.5 秒缩短为可配置值；非战斗时检测间隔 1 秒降为可配置值。
4. 并行模板匹配：路线节点、小地图、牌库和选卡页的卡牌类型都是在同一帧、同一区域里逐个匹配多种图标，
   请求组内第一个图标时整组并行算完并缓存，后续直接取结果；每个图标的计算与原来完全相同。
5. 路线页识别前原本固定等 1 秒让图标入场动画放完：改为至少等 0.4 秒、且连续两次识别到的图标位置一致就继续，
   最长仍是 1 秒；没识别到任何图标（Boss 节点）时等满 1 秒。
6. 删卡/复制卡翻牌库：滚动步长仍是原来的半行；每次滚动后不再固定等 0.5 秒，卡牌区域一停止移动就识别，
   没检测到移动时仍等满 0.5 秒。最下面一行卡的描述在区域外读不到，原规则会整行丢弃（实测只保留 3%），
   删卡/复制卡只需要卡名，所以这两种流程里图标匹配度 >0.9 且读到卡名即保留（沿用原本给咒术卡的规则）。
7. 要求移除多张但目标卡不够时：原逻辑会点“跳过”，连已选中的目标卡也不删；现在只要选中了至少 1 张，
   就不点“跳过”，交给原有的“移除”按钮处理确认删除已选中的卡（不拿其他卡凑数）。一张没选中仍照原逻辑跳过；
   若保留部分选择后“移除”按钮没点成，下一次照原逻辑跳过，避免反复。
8. 出击模式战斗出牌：原逻辑按数字键选中卡牌后固定等 0.5~1 秒才回车，回车后再固定等 1~2 秒。
   实测按键后 0.01~0.04 秒卡牌就上滑到位，回车后约 0.2~0.3 秒手牌数就减少了。
   改为按数字键后等手牌区出现明显变化（卡牌上滑）就回车，回车后等手牌数减少就继续；
   两段都以原时长封顶，判断不出结果（例如这张牌没打出去）时照原逻辑等满。
   有的牌打出后会弹出选择页面（如“请选择功能”），盖住手牌数：回车后连续几次读不到手牌数就结束等待，
   这次出牌流程剩下的按键也不再发送（兜底出牌会把手牌数到 1 的按键都按一遍），由下一轮马上处理弹窗。

只作用于卡厄思模式和出击模式，关闭任务配置里的“加速模式”即完全使用原逻辑。

注意：本文件不能定义顶层类，框架会把 ok_tasks 下含类的 .py 当作任务加载。
"""
import functools
import inspect
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

import config_io
import utils

ENABLE_KEY = "加速模式"
HOVER_KEY = "点击前悬停等待(秒)"
INTERVAL_KEY = "非战斗检测间隔(秒)"

_GRID = 10              # 文字中心按 10x10 网格量化后比较页面
_SAME_PAGE = 0.6        # 与点击前文字布局相似度 >= 0.6 视为页面还没响应
_STABLE = 0.75          # 相邻两次识别相似度 >= 0.75 视为文字已稳定
_BUTTON_TOLERANCE = 0.02
_GATE_INTERVAL = 0.05   # 闸门等待期间尽快再识别
_BATTLE_INTERVAL = 1.0  # 战斗中保持原逻辑的 1 秒，避免多占 CPU
_STATS_EVERY = 30
_EXPECTED_RUN_SOURCE = (
    "self.all_texts = _simplify_texts(self.ocr())",
    "self._check_upload_if_needed()",
)
# run() 里用的页面处理函数列表（卡厄思是 utils_chaos，出击是 utils_sortie）
_HANDLERS_PATTERN = re.compile(r"for handle_page in (\w+)\.PAGE_HANDLERS:")
# 战斗中的页面处理函数：检测间隔保持原逻辑的 1 秒，避免战斗时多占 CPU
_BATTLE_HANDLERS = frozenset((
    "handle_battle_auto_check",                                    # 卡厄思：等自动战斗
    "handle_battle_page", "handle_battle_hand_select", "handle_discard_hand_card",  # 出击：出牌
    "handle_curiosity_activate", "handle_extra_card_use", "handle_card_function_select",
    "handle_return_to_draw_pile",
))
# 处理函数会在同一帧、同一区域、同一阈值下依次匹配的图标组
_PARALLEL_GROUPS = (
    ("safezone", "enemy", "elite", "event", "settlement", "shop", "kalei", "seal", "hard"),  # 路线页节点与标记
    ("position_in_map", "settlement_in_map", "enemy_in_map", "safezoom_in_map", "elite_in_map",
     "event_in_map"),  # 小地图节点（阈值 0.85）
    ("kalei_in_map", "shop_in_map", "seal_in_map", "hard_in_map"),  # 小地图特殊标记（阈值 0.65）
    ("attack_in_deck", "skill_in_deck", "enhance_in_deck", "hex_in_deck", "hex_in_deck_tw"),  # 牌库卡牌类型
    ("attack", "skill", "enhance", "hex", "abnormal"),  # 选卡页卡牌类型
)
_GROUP_OF = {name: group for group in _PARALLEL_GROUPS for name in group}
_PREFETCH_KWARGS = {"feature_name", "box", "threshold"}
_match_pool = None
_ROUTE_TOLERANCE = 3        # 路线图标两次识别位置相差不超过 3 像素视为已停止入场动画
_ROUTE_MIN_SETTLE = 0.4     # 至少等 0.4 秒，防止图标依次出现时把“已出现的一部分”当成全部
_ROUTE_POLL = 0.05
_DECK_REGION = (0.274, 0.108, 0.929, 0.874)   # 与 recognize_cards_in_deck 的识别区域一致
_DECK_SIZE = (96, 112)      # 比较卡牌区域是否在动时用的缩略图尺寸
_DECK_MOVED = 0.03          # 与滚动前相比变化像素 >3%：列表已开始滚动
_DECK_STILL = 0.01          # 相邻两次截帧变化像素 <1%：列表已停
_DECK_POLL = 0.03
_NAME_ONLY_PAGES = ("select_card-移除", "select_card-复制")  # 只需要卡名的选卡流程
_NAME_ONLY_THRESHOLD = 0.90  # 与原本咒术卡的“只凭卡名保留”阈值一致
_SKIP_WORDS = ("跳过", "取消")  # 删卡流程找不够卡时原逻辑点的按钮
# 出击模式战斗出牌：按数字键选中卡牌（卡牌上滑），回车打出
_HAND_REGION = (0.159, 0.660, 0.836, 0.950)   # 手牌区域
_HAND_SIZE = (192, 96)
_HAND_MOVED = 0.15      # 手牌区相对按键前变化超过 15%：卡牌已上滑到位（实测 0.01~0.04 秒）
_HAND_POLL = 0.02
_RAISE_SETTLE = 0.05    # 上滑到位后再稍等一下才回车
_COUNT_REGION = (0.470, 0.950, 0.560, 0.995)  # 手牌数「N/10」
_COUNT_PATTERN = re.compile(r"(\d+)\s*/\s*10")
_PLAY_POLL = 0.04
_PLAY_SETTLE = 0.10     # 手牌数减少后再稍等一下，让出牌动画开始
_LEFT_BATTLE_POLLS = 3  # 回车后连续几次读不到手牌数：多半弹出了选择页面（如“请选择功能”），交给下一轮处理
_PARTIAL_RETRY_SECONDS = 10     # 保留部分选择后这段时间内再次进入选卡，视为“移除”没点成


def install(task):
    """给卡厄思模式任务实例装上加速逻辑，重复调用无副作用。"""
    if getattr(task, "_speedup", None) is not None:
        return
    task.default_config[ENABLE_KEY] = False
    task.default_config[HOVER_KEY] = 0.1
    task.default_config[INTERVAL_KEY] = 0.3
    task.config_description[ENABLE_KEY] = "实验性：点击后页面一响应就继续，不再固定等待；关闭时完全使用原逻辑"
    task.config_description[HOVER_KEY] = "仅在开启加速模式时生效：鼠标移到目标后等待多久再点击，原逻辑固定 0.5 秒"
    task.config_description[INTERVAL_KEY] = "仅在开启加速模式时生效：非战斗时两次识别的最短间隔，原逻辑 1 秒；战斗中保持 1 秒"
    # 加速选项只影响本机，不写进导出的配置码和上传的统计
    config_io.UI_ONLY_CONFIG_KEYS.update({ENABLE_KEY, HOVER_KEY, INTERVAL_KEY})

    orig = {
        name: getattr(task, name)
        for name in ("sleep", "click", "click_box", "move", "scroll", "mouse_down", "mouse_up", "send_key", "run",
                     "find_feature")
    }
    handlers = _handlers_module(task)
    st = {
        "orig_sleep": orig["sleep"], "active": False, "handlers": handlers, "gate_ok": handlers is not None,
        "in_run": False, "in_action": False, "owed_until": 0.0, "actions": 0,
        "moved": False, "held": False,
        "action_sig": None, "action_box": None, "action_time": 0.0,
        "gate": None, "prev_sig": None, "hit": None, "battle": False,
        "planned": 0.0, "actual": 0.0, "count": 0, "saved_total": 0.0,
        "match_cache": None, "deck_scroll": False, "deck_before": None,
        # 删卡目标不够时保留已选中的卡：kept_pending 为拦下“跳过”时已选中的张数，partial_at 为保留的时刻
        "removal_flow": False, "kept_pending": None, "allow_skip": False, "partial_at": 0.0,
        # 出击模式出牌：pay_hook 决定下一次补等待时怎么等（等卡牌上滑 / 等手牌数减少）
        "battle_play": False, "hand_before": None, "hand_count": None, "pay_hook": None,
        "battle_left": False,  # 出牌途中已离开战斗页面（弹出了选择页面）
    }
    task._speedup = st
    if not st["gate_ok"]:
        task.log_info(f"加速模式：{task.name} 的 run() 结构与 speedup.py 预期不一致，文字闸门已停用，其余优化照常")

    def sleep(timeout):
        if not st["active"] or timeout is None or timeout <= 0:
            return orig["sleep"](timeout)
        if st["battle_play"] and st["battle_left"]:
            return True  # 出牌途中已弹出选择页面：这次出牌流程剩下的等待不再需要
        if st["held"] or task.executor.paused:
            _pay_owed(st)
            return orig["sleep"](timeout)
        if st["moved"]:
            st["moved"] = False
            _pay_owed(st)
            hover = _float_config(task, HOVER_KEY, 0.1, 0.0, 1.0)
            st["saved_total"] += max(0.0, timeout - hover)
            return orig["sleep"](min(timeout, hover))
        # 连续多次 sleep 依次累加，与原逻辑串行等待一致
        st["owed_until"] = max(st["owed_until"], time.time()) + timeout
        task.executor.reset_scene(check_enabled=False)
        return True

    def action(name, point_of):
        def wrapped(*args, **kwargs):
            if not st["active"] or st["in_action"]:
                return orig[name](*args, **kwargs)
            st["in_action"] = True
            try:
                _pay_owed(st)  # 出牌时这里会判断上一张牌是否已打出、是否弹出了选择页面
                if name == "send_key" and st["battle_play"] and st["battle_left"]:
                    return True  # 出牌途中已弹出选择页面：剩下的出牌按键不再发送，交给下一轮处理弹窗
                if name == "mouse_down":
                    st["held"] = True
                    st["moved"] = False
                else:
                    if name == "mouse_up":
                        st["held"] = False
                    if name == "scroll" and st["deck_scroll"]:
                        # 牌库翻页：在欠的等待补完、真正滚动前截一帧，作为判断列表是否已滚动的参照
                        st["deck_before"] = _deck_capture(task)
                    if name == "send_key" and st["battle_play"]:
                        # 出牌：记下按键前的手牌区和手牌数，决定这次按键之后怎么等
                        _before_battle_key(task, st, args[0] if args else kwargs.get("key"))
                    _note_action(task, st, point_of(task, args, kwargs))
                return orig[name](*args, **kwargs)
            finally:
                st["in_action"] = False
        return wrapped

    def click_box(*args, **kwargs):
        if st["removal_flow"] and not st["allow_skip"]:
            box = args[0] if args else kwargs.get("box")
            name = getattr(box, "name", None)
            pending = getattr(task, "_pending_removed_card_count", 0)
            if pending > 0 and isinstance(name, str) and any(word in name for word in _SKIP_WORDS):
                # 删卡目标不够：已选中的目标卡照删，不点“跳过”，下一轮由原有的“移除”按钮处理确认
                st["kept_pending"] = pending
                task.log_info(f"加速：已选中{pending}张要移除的卡牌，不点「{name.strip()}」，改为确认移除已选中的卡牌")
                return True
        return orig["click_box"](*args, **kwargs)

    def move(*args, **kwargs):
        if st["active"]:
            _pay_owed(st)
            st["moved"] = True
        return orig["move"](*args, **kwargs)

    def find_feature(*args, **kwargs):
        name = kwargs.get("feature_name")
        group = _GROUP_OF.get(name) if isinstance(name, str) else None
        if group is None or args or not st["active"] or not set(kwargs) <= _PREFETCH_KWARGS:
            return orig["find_feature"](*args, **kwargs)
        key = (group, _box_key(kwargs.get("box")), kwargs.get("threshold", 0))
        common = {k: v for k, v in kwargs.items() if k != "feature_name"}
        if group is _PARALLEL_GROUPS[0] and st["owed_until"] > time.time():
            # 路线页：欠着的是识别前那 1 秒，用来等图标停稳，停稳即继续
            settled = _settle_route_icons(task, st, orig["find_feature"], group, common)
            if settled is not None:
                frame, results = settled
                st["match_cache"] = {"frame": frame, "key": key, "results": results}
                return list(results[name])
        # 与原逻辑取同一帧（取帧前会先补足欠的等待），整组在这一帧上并行匹配
        frame = task.executor.frame
        if frame is None:
            return orig["find_feature"](*args, **kwargs)
        cache = st["match_cache"]
        if cache is None or cache["frame"] is not frame or cache["key"] != key:
            cache = {"frame": frame, "key": key, "results": _match_group(orig["find_feature"], group, frame, common)}
            st["match_cache"] = cache
        return list(cache["results"][name])

    def run():
        _wrap_executor_next_frame(task.executor)
        enabled = _enabled(task)
        st.update(active=enabled, in_run=enabled, in_action=False, owed_until=0.0, actions=0,
                  moved=False, held=False, hit=None, action_sig=None, action_box=None, match_cache=None,
                  pay_hook=None, battle_play=False, battle_left=False)
        if not enabled:
            st.update(gate=None, prev_sig=None, battle=False)
            task.trigger_interval = 1
            return orig["run"]()
        failed = True
        try:
            if st["gate_ok"]:
                _gated_run(task, st)
            else:
                orig["run"]()
            failed = False
        finally:
            st["in_run"] = False
            if failed:
                st.update(owed_until=0.0, gate=None, active=False)
            else:
                _finish_run(task, st)
                st["active"] = False

    task.sleep = sleep
    task.click = action("click", _click_point)
    task.click_box = click_box
    task.scroll = action("scroll", _no_point)
    task.mouse_down = action("mouse_down", _no_point)
    task.mouse_up = action("mouse_up", _no_point)
    task.send_key = action("send_key", _no_point)
    task.move = move
    task.find_feature = find_feature
    task.run = run
    _keep_stuck_detection_at_one_second()
    _patch_deck_scan()
    _patch_partial_removal()
    _patch_battle_play()


def _handlers_module(task):
    """加速模式会接管 run()，只在其源码仍是“OCR -> 依次尝试页面处理函数 -> 上传检查”时启用闸门（修改 run() 后需同步 _gated_run）。
    页面处理函数列表取自 run() 里用的那个模块（卡厄思是 utils_chaos，出击是 utils_sortie）；对不上就返回 None。"""
    try:
        source = inspect.getsource(type(task).run)
    except (OSError, TypeError):
        return None
    match = _HANDLERS_PATTERN.search(source)
    if match is None or not all(snippet in source for snippet in _EXPECTED_RUN_SOURCE):
        return None
    module = sys.modules.get(type(task).__module__)
    handlers = getattr(module, match.group(1), None)
    return handlers if hasattr(handlers, "PAGE_HANDLERS") else None


def _gated_run(task, st):
    """与任务自己的 run() 相同，只在交给页面处理函数前多一道文字闸门。"""
    texts = utils._simplify_texts(task.ocr())
    if _gate_blocks(task, st, texts):
        return
    task.all_texts = texts
    for handle_page in st["handlers"].PAGE_HANDLERS:
        if handle_page(task):
            st["hit"] = handle_page.__name__
            return
    task._check_upload_if_needed()


def _finish_run(task, st):
    now = time.time()
    if st["owed_until"] > now:
        if st["gate_ok"] and st["actions"] == 1 and st["action_sig"] is not None:
            st["pay_hook"] = None  # 交给文字闸门，不再用出牌那套判断
            st["gate"] = {
                "sig": st["action_sig"], "box": st["action_box"],
                "start": st["action_time"], "until": st["owed_until"], "changed": False,
            }
            st["owed_until"] = 0.0
        else:
            _pay_owed(st)  # 多步操作或没有点击：保持原逻辑的等待时长
    if st["hit"] in _BATTLE_HANDLERS and not st["battle_left"]:
        st["battle"] = True  # 出牌后弹出了选择页面时不算战斗，下一轮按非战斗间隔尽快来处理
    elif st["hit"] is not None:
        st["battle"] = False
    if st["gate"] is not None:
        task.trigger_interval = _GATE_INTERVAL
    elif st["battle"]:
        task.trigger_interval = _BATTLE_INTERVAL
    else:
        task.trigger_interval = _float_config(task, INTERVAL_KEY, 0.3, 0.1, 1.0)


def _gate_blocks(task, st, texts):
    """返回 True 表示本轮先不交给页面处理函数。"""
    sig = _signature(task, texts)
    prev_sig, st["prev_sig"] = st["prev_sig"], sig
    gate = st["gate"]
    if gate is None:
        return False
    now = time.time()
    if now >= gate["until"]:
        _close_gate(task, st, now)
        return False
    if not gate["changed"]:
        if not _still_same_page(task, gate, texts, sig):
            gate["changed"] = True  # 页面刚变化，再识别一次确认已稳定
        return True
    if prev_sig is not None and _similarity(sig, prev_sig) >= _STABLE:
        _close_gate(task, st, now)
        return False
    return True


def _close_gate(task, st, now):
    gate, st["gate"] = st["gate"], None
    planned = gate["until"] - gate["start"]
    actual = now - gate["start"]
    st["planned"] += planned
    st["actual"] += actual
    st["count"] += 1
    st["saved_total"] += max(0.0, planned - actual)
    if st["count"] >= _STATS_EVERY:
        task.log_info(
            f"加速统计：最近{st['count']}次点击后的等待，原逻辑{st['planned']:.1f}秒，实际{st['actual']:.1f}秒"
        )
        task.info_set("加速累计节省", f"{st['saved_total'] / 60:.1f} 分钟")
        st.update(planned=0.0, actual=0.0, count=0)


def _still_same_page(task, gate, texts, sig):
    box = gate["box"]
    if box is not None:
        # 点的是文字按钮：按钮文字还在原处，说明游戏还没响应这次点击
        name, cx, cy = box
        dx, dy = _BUTTON_TOLERANCE * task.width, _BUTTON_TOLERANCE * task.height
        return any(
            b.name.strip() == name
            and abs(b.x + b.width / 2 - cx) <= dx
            and abs(b.y + b.height / 2 - cy) <= dy
            for b in texts
        )
    return _similarity(sig, gate["sig"]) >= _SAME_PAGE


def _note_action(task, st, point):
    st["actions"] += 1
    st["moved"] = False
    st["action_time"] = time.time()
    texts = getattr(task, "all_texts", None) or []
    st["action_sig"] = _signature(task, texts)
    st["action_box"] = None
    if point is not None:
        px, py = point
        hits = [b for b in texts if b.x <= px <= b.x + b.width and b.y <= py <= b.y + b.height and b.name.strip()]
        if hits:
            b = min(hits, key=lambda b: b.width * b.height)
            st["action_box"] = (b.name.strip(), b.x + b.width / 2, b.y + b.height / 2)


def _pay_owed(st):
    remaining = st["owed_until"] - time.time()
    hook, st["pay_hook"] = st["pay_hook"], None
    st["owed_until"] = 0.0
    if remaining <= 0:
        return
    # 出牌时按“游戏是否已响应”来等，最长仍是原来的时长；等不出结果就照原逻辑等满
    if hook is not None and hook(time.time() + remaining):
        return
    st["orig_sleep"](remaining)


def _wrap_executor_next_frame(executor):
    """处理函数取新画面前，先补足之前记账的等待。"""
    if getattr(executor, "_speedup_wrapped", False):
        return
    original = executor.next_frame

    def next_frame(*args, **kwargs):
        st = getattr(executor.current_task, "_speedup", None)
        if st is not None and st["in_run"] and not st["in_action"]:
            _pay_owed(st)
        return original(*args, **kwargs)

    executor.next_frame = next_frame
    executor._speedup_original_next_frame = original
    executor._speedup_wrapped = True


def _match_group(find_feature, group, frame, common):
    futures = {n: _pool().submit(find_feature, feature_name=n, frame=frame, **common) for n in group}
    return {n: f.result() for n, f in futures.items()}


def _icon_positions(results):
    return {n: sorted((b.x, b.y) for b in boxes) for n, boxes in results.items()}


def _same_positions(a, b):
    for name, points in a.items():
        other = b.get(name, [])
        if len(points) != len(other):
            return False
        if any(abs(x1 - x2) > _ROUTE_TOLERANCE or abs(y1 - y2) > _ROUTE_TOLERANCE
               for (x1, y1), (x2, y2) in zip(points, other)):
            return False
    return True


def _settle_route_icons(task, st, find_feature, group, common):
    """路线页识别前原本固定等 1 秒：改为反复截帧识别，至少 0.4 秒且连续两次图标位置一致就继续，最长仍是这 1 秒。
    没识别到任何图标（如 Boss 节点）时等满原时长。返回 (帧, 识别结果)；取不到帧时返回 None 交回原逻辑。"""
    capture = getattr(task.executor, "_speedup_original_next_frame", None)
    if capture is None:
        return None
    start = time.time()
    deadline, st["owed_until"] = st["owed_until"], 0.0
    previous = None
    while True:
        frame = capture()
        if frame is None:
            st["owed_until"] = deadline
            return None
        results = _match_group(find_feature, group, frame, common)
        positions = _icon_positions(results)
        if (previous is not None and any(positions.values()) and _same_positions(positions, previous)
                and time.time() - start >= _ROUTE_MIN_SETTLE):
            break
        previous = positions
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        st["orig_sleep"](min(_ROUTE_POLL, remaining))
    saved = max(0.0, deadline - time.time())
    st["saved_total"] += saved
    if saved > 0:
        task.log_info(f"加速：路线图标已停稳，识别前等待 {time.time() - start:.2f}s（原固定 {deadline - start:.2f}s）")
    return frame, results


def _active_state(task):
    st = getattr(task, "_speedup", None)
    return st if st is not None and st["active"] else None


def _capture(task):
    """截一帧；截不到时返回 None。"""
    capture = getattr(task.executor, "_speedup_original_next_frame", None)
    return capture() if capture is not None else None


def _thumbnail(frame, region, size):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = region
    area = frame[int(y1 * height):int(y2 * height), int(x1 * width):int(x2 * width)]
    return cv2.cvtColor(cv2.resize(area, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def _deck_capture(task):
    """截一帧并取卡牌区域的灰度缩略图；截不到帧时返回 None。"""
    frame = _capture(task)
    return None if frame is None else _thumbnail(frame, _DECK_REGION, _DECK_SIZE)


def _deck_changed(a, b):
    return np.count_nonzero(cv2.absdiff(a, b) > 12) / a.size


def _settle_deck(task, st, before):
    """滚动后原本固定等 0.5 秒：卡牌区域开始移动后，连续两次截帧几乎不变即视为停稳，提前结束等待；
    一直没检测到移动（例如已经到底）或截不到帧时，照原逻辑等满。"""
    deadline = st["owed_until"]
    if before is None or deadline <= time.time():
        return
    moved, previous, still = False, None, 0
    while time.time() < deadline:
        current = _deck_capture(task)
        if current is None:
            return
        if not moved:
            moved = _deck_changed(current, before) > _DECK_MOVED
        elif _deck_changed(current, previous) < _DECK_STILL:
            still += 1
            if still >= 2:
                st["saved_total"] += max(0.0, deadline - time.time())
                st["owed_until"] = 0.0
                return
        else:
            still = 0
        previous = current
        st["orig_sleep"](min(_DECK_POLL, max(0.0, deadline - time.time())))


def _patch_deck_scan():
    """包装 utils 里的牌库翻页滚动和卡牌识别；只在加速模式运行中、选卡流程里生效。"""
    if getattr(utils._scroll_card_page, "_speedup_wrapped", False):
        return
    orig_scroll = utils._scroll_card_page
    orig_recognize = utils._recognize_cards_by_features

    def _scroll_card_page(task, x, y, amount, page, *args, **kwargs):
        st = _active_state(task)
        if st is None or not str(page).startswith("select_card") or task.is_adb():
            return orig_scroll(task, x, y, amount, page, *args, **kwargs)
        st.update(deck_scroll=True, deck_before=None)
        try:
            result = orig_scroll(task, x, y, amount, page, *args, **kwargs)
        finally:
            st["deck_scroll"] = False
        before, st["deck_before"] = st["deck_before"], None
        _settle_deck(task, st, before)
        return result

    def _recognize_cards_by_features(*args, **kwargs):
        task = kwargs["task"] if "task" in kwargs else args[0]
        page = str(kwargs.get("page", ""))
        if _active_state(task) is not None and page.startswith(_NAME_ONLY_PAGES):
            # 删卡/复制卡只需要卡名：图标匹配度够高就不再要求类型和描述（最下面一行的描述在区域外）
            thresholds = dict(kwargs.get("name_only_feature_thresholds") or {})
            for feature_name in kwargs.get("feature_types") or {}:
                thresholds.setdefault(feature_name, _NAME_ONLY_THRESHOLD)
            kwargs["name_only_feature_thresholds"] = thresholds
        return orig_recognize(*args, **kwargs)

    for wrapper in (_scroll_card_page, _recognize_cards_by_features):
        wrapper._speedup_wrapped = True
    utils._scroll_card_page = _scroll_card_page
    utils._recognize_cards_by_features = _recognize_cards_by_features


def _patch_partial_removal():
    """包装 utils.select_card：要求移除多张但目标卡不够时，保留已选中的卡，交给原有的“移除”按钮处理确认删除。
    原逻辑翻到底仍不够就点“跳过”并把待移除计数清零；这里在删卡流程中拦下这一下点击（见 install 里的 click_box），
    结束后把计数恢复成已选中的张数，“移除”按钮处理据此记录删了几张。"""
    if getattr(utils.select_card, "_speedup_wrapped", False):
        return
    orig_select = utils.select_card

    def select_card(task, *args, **kwargs):
        st = _active_state(task)
        action = kwargs.get("action", args[2] if len(args) > 2 else "")
        if st is None or action != "移除":
            return orig_select(task, *args, **kwargs)
        # 上次保留了部分选择，计数却没被“移除”按钮处理清零：说明没能确认，这次照原逻辑跳过，避免反复选卡
        retry = (getattr(task, "_pending_removed_card_count", 0) > 0
                 and time.time() - st["partial_at"] < _PARTIAL_RETRY_SECONDS)
        if retry:
            task.log_info("加速：上次保留的已选卡牌没有移除成功，本次照原逻辑处理")
        st.update(removal_flow=True, allow_skip=retry, kept_pending=None, partial_at=0.0)
        try:
            result = orig_select(task, *args, **kwargs)
        finally:
            st["removal_flow"] = False
        kept, st["kept_pending"] = st["kept_pending"], None
        if kept is not None:
            task._pending_removed_card_count = kept
            st["partial_at"] = time.time()
        return result

    select_card._speedup_wrapped = True
    utils.select_card = select_card


def _patch_battle_play():
    """出击模式战斗出牌：原逻辑按数字键后固定等 0.5~1 秒才回车，回车后再固定等 1~2 秒。
    实测卡牌按下后 0.01~0.04 秒就上滑到位，回车后约 0.2~0.3 秒手牌数就减少了。
    这里把两段等待都改成“游戏一响应就继续”，最长仍是原来的时长；判断不出结果时照原逻辑等满。"""
    try:
        import utils_sortie
    except ImportError:
        return
    handlers = getattr(utils_sortie, "PAGE_HANDLERS", None)
    for name in ("handle_battle_page", "_try_all_card_keys"):
        current = getattr(utils_sortie, name, None)
        if current is None:
            continue
        if not getattr(current, "_speedup_wrapped", False):
            current = _battle_play_wrapper(current)
            setattr(utils_sortie, name, current)
        # 页面处理函数列表里存的是函数对象本身，只换模块属性不会生效，列表里的也要换成包装后的
        if isinstance(handlers, list):
            handlers[:] = [current if h is current.__wrapped__ else h for h in handlers]


def _battle_play_wrapper(original):
    @functools.wraps(original)  # 保留原函数名：检测间隔按处理函数名判断是否在战斗中
    def wrapped(task, *args, **kwargs):
        st = _active_state(task)
        if st is None:
            return original(task, *args, **kwargs)
        previous = st["battle_play"]
        st.update(battle_play=True, battle_left=False)
        try:
            return original(task, *args, **kwargs)
        finally:
            # battle_left 保留到本轮结束：_finish_run 据此让下一轮尽快来处理弹窗；下一轮开始时复位
            st.update(battle_play=previous, hand_before=None, hand_count=None)

    wrapped._speedup_wrapped = True
    return wrapped


def _before_battle_key(task, st, key):
    """按键前记下参照，并决定这次按键之后怎么补等待。"""
    key = str(key or "").lower()
    st["pay_hook"] = None
    if key.isdigit():
        frame = _capture(task)
        if frame is None:
            return
        hand = _thumbnail(frame, _HAND_REGION, _HAND_SIZE)
        st["hand_count"] = _hand_count(task, frame)
        st["pay_hook"] = lambda deadline: _wait_card_raised(task, st, hand, deadline)
    elif key == "enter" and st["hand_count"]:
        before = st["hand_count"]
        st["pay_hook"] = lambda deadline: _wait_card_played(task, st, before, deadline)


def _hand_count(task, frame):
    """读手牌数「N/10」；读不到返回 None。"""
    try:
        for box in task.ocr(*_COUNT_REGION, frame=frame):
            match = _COUNT_PATTERN.search(box.name)
            if match:
                return int(match.group(1))
    except Exception:
        return None
    return None


def _wait_card_raised(task, st, reference, deadline):
    """按数字键后等卡牌上滑到位，到位就可以回车。"""
    while time.time() < deadline:
        frame = _capture(task)
        if frame is None:
            return False
        if _deck_changed(_thumbnail(frame, _HAND_REGION, _HAND_SIZE), reference) > _HAND_MOVED:
            st["orig_sleep"](min(_RAISE_SETTLE, max(0.0, deadline - time.time())))
            st["saved_total"] += max(0.0, deadline - time.time())
            return True
        st["orig_sleep"](min(_HAND_POLL, max(0.0, deadline - time.time())))
    return True  # 没检测到上滑：已经等满原时长


def _wait_card_played(task, st, before, deadline):
    """回车后等手牌数减少，说明卡牌已经打出去了。
    手牌数连续几次都读不到时，多半是这张牌弹出了选择页面（如“请选择功能”）盖住了手牌区：
    结束等待并标记，这次出牌流程剩下的按键不再发送，由下一轮去处理弹窗。"""
    missing = 0
    while time.time() < deadline:
        frame = _capture(task)
        if frame is None:
            return False
        count = _hand_count(task, frame)
        if count is not None and count < before:
            st["hand_count"] = count
            st["orig_sleep"](min(_PLAY_SETTLE, max(0.0, deadline - time.time())))
            st["saved_total"] += max(0.0, deadline - time.time())
            return True
        missing = missing + 1 if count is None else 0
        if missing >= _LEFT_BATTLE_POLLS:
            st["battle_left"] = True
            st["saved_total"] += max(0.0, deadline - time.time())
            task.log_info("加速：出牌后读不到手牌数，多半弹出了选择页面，停止这次出牌流程，先处理页面")
            return True
        st["orig_sleep"](min(_PLAY_POLL, max(0.0, deadline - time.time())))
    return True  # 手牌数没减少（例如这张牌没打出去）：已经等满原时长


def _signature(task, texts):
    width, height = task.width or 1, task.height or 1
    return {
        (b.name.strip(), int((b.x + b.width / 2) / width * _GRID), int((b.y + b.height / 2) / height * _GRID))
        for b in texts
        if b.name.strip()
    }


def _similarity(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _click_point(task, args, kwargs):
    """把 click() 的参数换算成像素坐标；Box、相对坐标、像素坐标三种写法都支持。"""
    x = args[0] if args else kwargs.get("x", -1)
    y = args[1] if len(args) > 1 else kwargs.get("y", -1)
    if isinstance(x, list):
        x = x[0] if x else None
    if hasattr(x, "width") and hasattr(x, "x"):
        return x.x + x.width / 2, x.y + x.height / 2
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    if 0 < x < 1 or 0 < y < 1:
        return x * task.width, y * task.height
    return (x, y) if x >= 0 and y >= 0 else None


def _no_point(task, args, kwargs):
    return None


def _pool():
    global _match_pool
    if _match_pool is None:
        _match_pool = ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4), thread_name_prefix="speedup-match")
    return _match_pool


def _box_key(box):
    if box is None or isinstance(box, str):
        return box
    return box.x, box.y, box.width, box.height


def _enabled(task):
    try:
        return bool(task.config.get(ENABLE_KEY, False))
    except Exception:
        return True


def _float_config(task, key, default, low, high):
    try:
        value = float(task.config.get(key, default))
    except (TypeError, ValueError, AttributeError):
        value = default
    return min(high, max(low, value))


def _keep_stuck_detection_at_one_second():
    """卡死检测按“相邻两次检测的画面变化”判断，检测变密后仍保持约 1 秒采样一次，避免误判卡死。"""
    original = utils.is_frame_stuck
    if getattr(original, "_speedup_wrapped", False):
        return

    def is_frame_stuck(task, stuck_threshold_seconds=30, change_threshold=0.08):
        now = time.time()
        if now - getattr(task, "_speedup_stuck_sample", 0.0) < 0.9 and hasattr(task, "_last_change_time"):
            return now - task._last_change_time >= stuck_threshold_seconds
        task._speedup_stuck_sample = now
        return original(task, stuck_threshold_seconds, change_threshold)

    is_frame_stuck._speedup_wrapped = True
    utils.is_frame_stuck = is_frame_stuck
