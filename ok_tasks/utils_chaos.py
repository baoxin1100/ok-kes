from ok import TriggerTask

from utils import (
    _move_and_click, _simplify_texts, _get_config_value, _get_card_list, _get_route_priority, _get_game_text, _get_region_text, _get_current_hp_percent, _finish_only_first_layer,
    find_box_at_point, find_text, recognize_cards, find_target_card,
    _card_has_type_below, select_card, recognize_cards_in_deck, _scroll_to_target_member_for_card_removal,
    log_credit, log_node_status, handle_battle_crash, handle_close_page, handle_refine_equipment_credit,
    handle_center_confirm, handle_settlement, handle_skip,
    handle_destiny_choice, handle_main_member_flash,
    handle_card_reward, handle_equipment,
    handle_select_card, handle_copy_card_choice, handle_copy_member,
    handle_convert_card,
    handle_negotiation, handle_continue, handle_confirm, handle_enter,
    handle_event_task, handle_route_selection, handle_obtain_reward,
    handle_leave, handle_next_step, handle_select, handle_rest, handle_view_original, handle_weakness_info,
    handle_close_button,
    handle_card_assign, handle_non_battle_page, handle_minimizemap, handle_held_cards_page, handle_craft,
    handle_remove, handle_three_choice_card_remove, handle_flash, handle_reflash, handle_grant_flash, handle_copy, handle_convert,
    handle_equipment_recast,
    handle_stuck_log, handle_expedition_result,
    is_button_active, is_subsequence, _clean_match,
    handle_shop,
    handle_escape,
    # handle_stage_clear,
    handle_auto_stop,
    _is_engraving_farm_enabled,
    _detect_engraving_icon,
    _match_engraving_template,
    _extract_engraving_description,
    _engraving_priority,
    _match_engraving_text,
    _equipment_state,
)

import re
import random
import time
import os

import cv2
import numpy as np


# ------------------------- 卡厄思模式独有页面处理函数 -------------------------


def handle_keyword_pause(task: TriggerTask):
    """OCR命中配置关键词时暂停自动操作，等待用户手动接管。"""
    keywords = [keyword.strip() for keyword in re.split(r"[,，;；]", _get_config_value(task, "关键词暂停", "")) if keyword.strip()]
    if not keywords:
        return False
    match = next(((keyword, box) for box in task.all_texts for keyword in keywords if keyword in box.name), None)
    if match is None:
        return False
    keyword, matched_box = match
    task.log_info(f"命中暂停关键词「{keyword}」，OCR文本「{matched_box.name}」，暂停工具等待手动接管")
    task.executor.pause()
    return True


def _get_memory_process_keywords(task: TriggerTask):
    """获取加工记忆词条关键字列表（优先读取“加工记忆词条”，兼容“指定记忆卡牌”）。"""
    raw = _get_config_value(task, "加工记忆词条", "")
    if not raw:
        raw = _get_config_value(task, "指定记忆卡牌", "")
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    elif isinstance(raw, str):
        items = re.split(r"[,，;；]+", raw)
    else:
        items = []
    keywords = []
    for item in items:
        cleaned = re.sub(r"\s+", "", item)
        if cleaned:
            keywords.append(cleaned)
    return keywords


def _card_matches_memory_keywords(card, keywords):
    """检查单张记忆卡牌的名称与描述是否命中任一目标词条关键字。"""
    combined = re.sub(r"\s+", "", f"{card.get('name', '')}：:{card.get('description', '')}")
    for kw in keywords:
        if is_subsequence(kw, combined):
            return kw
    return None


_EVENT_CRYSTAL_TEMPLATE = None


def _load_event_crystal_template(task: TriggerTask):
    """加载事件场景晶石图标模板，并按当前分辨率缩放。"""
    global _EVENT_CRYSTAL_TEMPLATE
    if _EVENT_CRYSTAL_TEMPLATE is None:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "assets",
            "images",
            "event_crystal.png",
        )
        template = cv2.imdecode(
            np.fromfile(template_path, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if template is None:
            task.log_info(f"事件晶石模板读取失败：{template_path}")
            return None
        _EVENT_CRYSTAL_TEMPLATE = template
    template = _EVENT_CRYSTAL_TEMPLATE
    scale_x = task.width / 1600
    scale_y = task.height / 900
    if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
        template = cv2.resize(
            template,
            (
                max(1, int(round(template.shape[1] * scale_x))),
                max(1, int(round(template.shape[0] * scale_y))),
            ),
            interpolation=cv2.INTER_AREA,
        )
    return template


def handle_event_crystal(task: TriggerTask):
    """事件场景中的晶石收集物：识别并点击。"""
    if task.frame is None:
        return False
    if time.time() - task.node_status.get("event_crystal_last_click", 0) < 2:
        return False
    template = _load_event_crystal_template(task)
    if template is None:
        return False
    frame = task.frame[:, :, :3]
    height, width = frame.shape[:2]
    # 事件场景中央区域：覆盖 19 图的中上位置和 20 图的中下位置，避开底部选项
    x1, y1 = int(width * 0.30), int(height * 0.22)
    x2, y2 = int(width * 0.80), int(height * 0.72)
    region = frame[y1:y2, x1:x2]
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return False
    result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, max_value, _, max_location = cv2.minMaxLoc(result)
    if max_value < 0.75:
        task.node_status["event_crystal_clicks"] = 0
        return False
    clicks = task.node_status.get("event_crystal_clicks", 0)
    if clicks >= 3:
        return False
    center_x = (x1 + max_location[0] + template.shape[1] / 2) / width
    center_y = (y1 + max_location[1] + template.shape[0] / 2) / height
    task.node_status["event_crystal_clicks"] = clicks + 1
    task.node_status["event_crystal_last_click"] = time.time()
    task.log_info(
        f"事件场景：识别到晶石收集物（相似度{max_value:.3f}），"
        f"第{clicks + 1}次点击 ({center_x:.3f}, {center_y:.3f})"
    )
    _move_and_click(task, center_x, center_y)
    task.sleep(0.8)
    return True


def handle_flash_effect_no_card(task: TriggerTask):
    """闪光效果页面卡牌未渲染时，等待10秒后点击最左卡牌位置兜底。"""
    title = _get_region_text(task, (0.300, 0.080, 0.720, 0.230))
    if _get_game_text(task, "请决定闪光效果") not in title:
        task.node_status.pop("flash_effect_no_card_since", None)
        return False

    if recognize_cards(task, page="闪光效果兜底") or []:
        task.node_status.pop("flash_effect_no_card_since", None)
        return False

    now = time.time()
    started = task.node_status.get("flash_effect_no_card_since")
    if not started:
        task.node_status["flash_effect_no_card_since"] = now
        task.log_info("闪光效果页面：只有标题未识别到卡牌，等待10秒后点击最左卡牌位置")
        return True
    waited = now - started
    if waited < 10:
        return True

    task.node_status.pop("flash_effect_no_card_since", None)
    task.log_info(f"闪光效果页面：已等待{waited:.0f}秒仍无卡牌，点击最左卡牌位置兜底")
    _move_and_click(task, 0.245, 0.495)
    task.sleep(1)
    return True


def handle_meditation_card_select(task: TriggerTask):
    """冥想选卡页：优先选择目标主战员行内最左侧的钉针卡。"""
    title = _get_region_text(task, (0.080, 0.015, 0.550, 0.085))
    if "想要重新闪光" not in title:
        task.node_status["meditation_card_selected"] = False
        return False

    if task.node_status.get("meditation_card_selected"):
        if time.time() - task.node_status.get("meditation_card_click_time", 0) < 4:
            return True
        task.node_status["meditation_card_selected"] = False

    # 先滚动到配置的目标主战员
    _scroll_to_target_member_for_card_removal(task)

    deck_region = (0.274, 0.108, 0.929, 0.874)
    pins = task.find_feature(
        feature_name="targetinselectcard",
        box=task.box_of_screen(*deck_region),
        threshold=0.75,
    ) or []
    if not pins:
        return False

    cards = recognize_cards_in_deck(task, page="冥想选卡页面")
    if not cards:
        task.log_info("冥想选卡页面：识别到钉针但未识别到卡牌，交给通用选卡处理")
        return False

    candidates = []
    for pin in pins:
        pin_x = (pin.x + pin.width / 2) / task.width
        pin_y = (pin.y + pin.height / 2) / task.height
        left_cards = [
            card
            for card in cards
            if abs(
                (card["feature_box"].y + card["feature_box"].height / 2) / task.height
                - pin_y
            ) <= 0.15
            and (
                card["feature_box"].x + card["feature_box"].width / 2
            ) / task.width < pin_x
        ]
        if not left_cards:
            continue
        card = max(
            left_cards,
            key=lambda item: item["feature_box"].x + item["feature_box"].width / 2,
        )
        candidates.append((pin_x, pin_y, card))
    if not candidates:
        return False

    if task.feature_exists("target_member_in_select_card"):
        target_member = task.find_one(
            feature_name="target_member_in_select_card",
            box=task.box_of_screen(0.079, 0.092, 0.209, 0.675),
            threshold=0.5,
        )
        if target_member:
            row_y = (target_member.y + target_member.height / 2) / task.height
            row_candidates = [
                candidate
                for candidate in candidates
                if abs(candidate[2]["y"] - row_y) <= 0.15
            ]
            if row_candidates:
                candidates = row_candidates
            else:
                task.log_info("冥想选卡页面：目标主战员行内没有钉针卡，按全部钉针选择")

    flash_priority = _get_card_list(task, "闪光优先级")

    def matched_priority(card):
        combined = f"{card['name']}：:{card['description']}"
        return next(
            (
                keyword.strip()
                for keyword in flash_priority
                if isinstance(keyword, str)
                and keyword.strip()
                and is_subsequence(keyword.strip(), combined)
            ),
            None,
        )

    unmatched = [
        candidate for candidate in candidates if not matched_priority(candidate[2])
    ]
    pool = unmatched or candidates
    pool.sort(key=lambda candidate: candidate[2]["feature_box"].x)
    chosen = pool[0][2]
    task.log_info(
        f"冥想选卡页面：选择钉针卡「{chosen['name']}」"
        f"（{'未命中' if unmatched else '已全部命中'}闪光优先级）"
    )
    _move_and_click(task, chosen["x"], chosen["y"])
    task.sleep(0.5)
    task.node_status["meditation_card_selected"] = True
    task.node_status["meditation_card_click_time"] = time.time()
    return True


def handle_memory_process(task: TriggerTask):
    """加工记忆（记忆加工）页面：选择命中加工记忆词条的卡牌并确认返回，未命中则跳过。"""
    title = _get_region_text(task, (0.400, 0.070, 0.600, 0.175)).replace(" ", "")
    process_title_keywords = {"加工记忆", "记忆加工", _get_game_text(task, "加工记忆")}
    if not any(kw in title for kw in process_title_keywords if kw):
        return False

    task.log_info("检测到记忆加工页面")
    status = getattr(task, "node_status", None)
    if isinstance(status, dict):
        status["memory_process_done"] = True
        status["precision_memory_visited"] = True

    def find_confirm_btn():
        return next(
            (
                b for b in task.all_texts
                if 0.780 <= (b.x + b.width / 2) / task.width <= 0.995
                and 0.880 <= (b.y + b.height / 2) / task.height <= 0.985
                and "确认" in b.name
            ),
            None,
        )

    def is_memory_confirm_orange():
        patch = task.frame[
            int(0.910 * task.height):int(0.960 * task.height),
            int(0.800 * task.width):int(0.980 * task.width),
            :3,
        ]
        if patch.size == 0:
            return False
        blue, _, red = patch.mean(axis=(0, 1))
        return (red - blue) > 40

    # 若已经点过确认、进入单张新词条卡牌居中展示界面（无右下角确认按钮），点击任意区域返回图1
    confirm_box = find_confirm_btn()
    if confirm_box is None:
        cards_now = recognize_cards(
            task, region=(0.095, 0.204, 0.887, 0.450), page="加工记忆页面"
        )
        if len(cards_now) <= 1:
            task.log_info("记忆加工页面：检测到新词条单卡展示界面，点击返回记忆雕琢界面")
            _move_and_click(task, 0.500, 0.900)
            task.sleep(1.2)
            return True

    # 若已选中卡牌使右下角确认按钮变为橙色激活状态（图3），点击确认并点击空白处返回图1
    if confirm_box and is_memory_confirm_orange():
        task.log_info("记忆加工页面：确认按钮已变黄激活，点击确认转换词条")
        task.click_box(confirm_box)
        task.sleep(1.8)
        task.log_info("记忆加工页面：点击屏幕返回记忆雕琢界面")
        _move_and_click(task, 0.500, 0.900)
        task.sleep(1.2)
        return True

    keywords = _get_memory_process_keywords(task)
    cards = []
    chosen_card = None
    matched_kw = None
    for attempt in range(3):
        if attempt > 0:
            task.sleep(0.8)
            task.all_texts = _simplify_texts(task.ocr())
        cards = recognize_cards(
            task, region=(0.095, 0.204, 0.887, 0.450), page="加工记忆页面"
        )[:3]
        if keywords:
            for card in cards:
                kw = _card_matches_memory_keywords(card, keywords)
                if kw:
                    chosen_card = card
                    matched_kw = kw
                    break
        if chosen_card or len(cards) >= 3:
            break

    if chosen_card:
        task.log_info(
            f"记忆加工页面：命中加工记忆词条「{matched_kw}」，点击选择「{chosen_card['name']}」"
        )
        _move_and_click(task, chosen_card["x"], chosen_card["y"])
        task.sleep(0.8)
        task.all_texts = _simplify_texts(task.ocr())
        confirm_box = find_confirm_btn()
        if confirm_box:
            task.log_info("记忆加工页面：点击右下角确认按钮")
            task.click_box(confirm_box)
        else:
            task.log_info("记忆加工页面：点击右下角固定确认位置")
            _move_and_click(task, 0.885, 0.935)
        task.sleep(1.8)
        task.log_info("记忆加工页面：点击屏幕关闭新词条展示，返回记忆雕琢界面")
        _move_and_click(task, 0.500, 0.900)
        task.sleep(1.2)
        return True

    task.log_info("记忆加工页面：未匹配到目标加工记忆词条，点击跳过返回记忆雕琢界面")
    _move_and_click(task, 0.762, 0.935)
    task.sleep(1.2)
    return True


def _find_memory_refresh_actions(task: TriggerTask):
    """在记忆卡牌选择页面查找底部三列的重新搜索按钮及剩余次数。"""
    refresh_keywords = {
        "重新搜索",
        _get_game_text(task, "重新搜索"),
        _get_game_text(task, "刷新"),
    }
    search_boxes = []
    count_boxes = []
    for box in task.all_texts:
        x = (box.x + box.width / 2) / task.width
        y = (box.y + box.height / 2) / task.height
        if not (0.109 <= x <= 0.880 and 0.779 <= y <= 0.874):
            continue
        if any(kw in box.name for kw in refresh_keywords if kw):
            search_boxes.append(box)
        match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", box.name)
        if match:
            count_boxes.append((box, int(match.group(1))))

    actions = []
    unused_search = list(search_boxes)
    for count_box, remaining in sorted(count_boxes, key=lambda item: item[0].x)[:3]:
        count_x = count_box.x + count_box.width / 2
        count_y = count_box.y + count_box.height / 2
        candidates = [
            box for box in unused_search
            if box.x + box.width / 2 < count_x
            and abs(box.y + box.height / 2 - count_y) <= 0.04 * task.height
        ]
        if not candidates:
            continue
        search_box = min(
            candidates,
            key=lambda box: (box.x + box.width / 2 - count_x) ** 2
            + (box.y + box.height / 2 - count_y) ** 2,
        )
        unused_search.remove(search_box)
        actions.append((search_box, count_box, remaining))
    return actions, count_boxes


def handle_memory_card_select(task: TriggerTask):
    """记忆卡牌选择页面：优先target钉子标记卡牌，其次指定记忆卡牌，否则刷新；三列5次刷新用尽仍未命中则退出战斗重来。"""
    title = _get_region_text(task, (0.341, 0.011, 0.670, 0.171))
    if _get_game_text(task, "选择铭刻的记忆") not in title:
        return False

    task.log_info("检测到记忆卡牌选择页面，等待1秒让卡面与刷新按钮稳定")
    task.sleep(1)
    task.all_texts = _simplify_texts(task.ocr())
    specified_memory = _get_config_value(task, "指定记忆卡牌", "")

    cards = []
    actions = []
    count_boxes = []
    # 卡面与底部刷新按钮存在约1秒动画延迟，进行多次检测以防卡面或刷新按钮尚未加载完成
    for attempt in range(3):
        cards = recognize_cards(
            task, region=(0.065, 0.176, 0.931, 0.432), page="记忆卡牌选择页面"
        )
        target_boxes, target_click_positions = find_target_card(task)
        if target_boxes:
            task.log_info("记忆卡牌选择页面：检测到target卡牌，优先选择")
            if hasattr(task, "node_status") and isinstance(task.node_status, dict):
                task.node_status["memory_escape_pending"] = False
            task._memory_escape_tried_esc = False
            _move_and_click(task, *target_click_positions[0])
            task.sleep(1)
            return True

        if specified_memory:
            for card in cards:
                if is_subsequence(specified_memory, card["name"] + "：:" + card["description"]):
                    task.log_info(f"记忆卡牌选择页面：命中指定记忆卡牌「{card['name']}」")
                    if hasattr(task, "node_status") and isinstance(task.node_status, dict):
                        task.node_status["memory_escape_pending"] = False
                    task._memory_escape_tried_esc = False
                    _move_and_click(task, card["x"], card["y"])
                    task.sleep(1)
                    return True

        actions, count_boxes = _find_memory_refresh_actions(task)
        all_exhausted = len(count_boxes) >= 3 and all(rem == 0 for _, rem in count_boxes[:3])
        if len(cards) >= 3 and (len(actions) >= 3 or all_exhausted):
            break
        if attempt < 2:
            task.log_info(
                f"记忆卡牌选择页面：等待卡面与刷新按钮加载（第{attempt + 1}次重试，当前卡面={len(cards)}，刷新按钮={len(actions)}）"
            )
            task.sleep(1)
            task.all_texts = _simplify_texts(task.ocr())

    refreshed = False
    for search_box, count_box, remaining in actions:
        if remaining == 0:
            continue
        task.log_info(f"记忆卡牌选择页面：剩余搜索次数={remaining}，点击重新搜索")
        _move_and_click(
            task,
            (search_box.x + search_box.width / 2) / task.width,
            (search_box.y + search_box.height / 2) / task.height,
        )
        task.sleep(1)
        refreshed = True
    if refreshed:
        # 刷新后额外等待1.5秒，确保新卡面及晚1秒出现的刷新按钮完整刷新出来
        task.sleep(1.5)
    else:
        if hasattr(task, "node_status") and isinstance(task.node_status, dict):
            task.node_status["memory_escape_pending"] = True
        if not getattr(task, "_memory_escape_tried_esc", False):
            task._memory_escape_tried_esc = True
            task.log_info(
                "记忆卡牌选择页面：三列刷新次数已全部用完且未命中目标记忆卡牌，点击右上角ESC尝试退出本局重来"
            )
            _move_and_click(task, 0.959, 0.053)
            task.sleep(1.5)
            return True
        if cards:
            card = random.choice(cards)
            task.log_info(
                f"记忆卡牌选择页面：弹窗内无法直接呼出菜单，先选择「{card['name']}」关闭弹窗，随后立即执行退出本局重来"
            )
            _move_and_click(task, card["x"], card["y"])
            task.sleep(1)
    return True


def handle_pending_memory_escape(task: TriggerTask):
    """当记忆卡牌5次刷新均未刷到指定记忆卡牌时，关闭选卡分配弹窗后立即点击右上角菜单执行逃脱重来。"""
    node_status = getattr(task, "node_status", None)
    if not isinstance(node_status, dict):
        return False
    if not node_status.get("memory_escape_pending", False):
        return False
    if node_status.get("is_escaped", False):
        node_status["memory_escape_pending"] = False
        return False

    # 确认已回到顶部状态栏可见的常规界面（生命值可读或位于路线选择/事件对话页面）
    if _get_current_hp_percent(task) is False:
        return False

    task.log_info("未刷到指定记忆卡牌，触发退出战斗重来：点击右上角菜单按钮")
    _move_and_click(task, 0.959, 0.053)
    task.sleep(1.5)
    return True


def _match_storage_data_value(task: TriggerTask, text: str):
    """匹配当前游戏语言中的“存储数据价值+数字”或“数字+pt”，不要求末尾层级文本。"""
    storage_data_text = re.escape(_get_game_text(task, "存储数据"))
    match = re.search(
        rf"(?:{storage_data_text}|存储数据|存档资料|保存上限|储存上限)[^0-9]*?(\d+)",
        text,
    )
    if match:
        return match
    return re.search(r"(\d+)\s*[pP][tT]", text)


def _get_season_chaos_currency(task: TriggerTask):
    """读取赛季卡厄思初始页面右上角的赛季货币数量（忽略左侧形如4/4的入场券）。"""
    candidates = []
    for box in getattr(task, "all_texts", []) or []:
        cx = (box.x + box.width / 2) / task.width
        cy = (box.y + box.height / 2) / task.height
        if 0.775 <= cx <= 0.875 and 0.025 <= cy <= 0.085:
            raw = box.name.strip()
            if "/" in raw or "+" in raw:
                continue
            cleaned = re.sub(r"[,\s]", "", raw)
            if cleaned.isdigit():
                candidates.append((cx, int(cleaned)))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return None


def _get_observe_cost(task: TriggerTask, default=10):
    """读取再次观测按钮右侧消耗的赛季货币数量，默认10。"""
    for box in getattr(task, "all_texts", []) or []:
        cx = (box.x + box.width / 2) / task.width
        cy = (box.y + box.height / 2) / task.height
        if 0.900 <= cx <= 0.985 and 0.750 <= cy <= 0.845:
            cleaned = re.sub(r"[,\s]", "", box.name.strip())
            if cleaned.isdigit():
                return int(cleaned)
    return default


def _reset_season_observe_state(task: TriggerTask):
    """重置赛季卡厄思再次观测防卡死状态。"""
    task._season_observe_clicked = False
    task._season_observe_last_sig = None
    task._season_observe_unchanged_count = 0
    task._season_observe_exhausted = False


def handle_season_chaos_initial_page(task: TriggerTask):
    """赛季卡厄思初始页面：存储数据价值层级(pt)不足时再次观测，含赛季货币不足与防卡死保护。"""
    title_text = _get_region_text(task, (0.075, 0.014, 0.305, 0.090))
    if "卡厄思" not in title_text:
        return False

    observe_region = (0.659, 0.715, 0.993, 0.851)
    observe_boxes = [
        box for box in task.all_texts
        if observe_region[0] <= (box.x + box.width / 2) / task.width <= observe_region[2]
        and observe_region[1] <= (box.y + box.height / 2) / task.height <= observe_region[3]
        and "再次观测" in box.name
    ]
    if not observe_boxes:
        return False

    task.log_info("检测到赛季卡厄思初始页面")
    value_text = _get_region_text(task, (0.684, 0.308, 0.982, 0.754))
    value_match = _match_storage_data_value(task, value_text)
    if not value_match:
        task.log_info(f"未识别到存储数据价值层级，区域文本=「{value_text}」")
        return False

    data_value_level = int(value_match.group(1))
    required_level = int(
        _get_config_value(task, "存储数据保存上限大于多少", 120)
    )
    task.log_info(
        f"当前存储数据保存上限={data_value_level}pt，"
        f"要求大于等于{required_level}pt"
    )
    if data_value_level >= required_level:
        _reset_season_observe_state(task)
        return False

    if getattr(task, "_season_observe_exhausted", False):
        task.log_info("已判定当前赛季货币不足以继续再次观测，跳过刷新直接进入")
        return False

    # 1. 检测屏幕中是否弹出「XX不足，无法再次观测」提示
    if any(
        "无法再次观测" in box.name or ("不足" in box.name and "观测" in box.name)
        for box in task.all_texts
    ):
        task.log_info("检测到「无法再次观测」弹窗提示，赛季货币不足，停止刷新直接进入")
        task._season_observe_exhausted = True
        return False

    # 2. 检测右上角赛季货币数量是否足够支付再次观测费用（默认10）
    observe_cost = _get_observe_cost(task, default=10)
    season_currency = _get_season_chaos_currency(task)
    if season_currency is not None:
        task.log_info(f"赛季卡厄思初始页面：当前赛季货币={season_currency}，再次观测消耗={observe_cost}")
        if season_currency < observe_cost:
            task.log_info(
                f"当前赛季货币({season_currency})少于再次观测所需({observe_cost})，停止刷新直接进入"
            )
            task._season_observe_exhausted = True
            return False

    # 3. 防卡死兜底：比对连续刷新前后的 pt 与下方词条文本是否变化
    current_sig = (data_value_level, value_text)
    if getattr(task, "_season_observe_clicked", False):
        if current_sig == getattr(task, "_season_observe_last_sig", None):
            unchanged = getattr(task, "_season_observe_unchanged_count", 0) + 1
            task._season_observe_unchanged_count = unchanged
            task.log_info(f"再次观测后pt与词条未发生变化（连续{unchanged}次）")
            if unchanged >= 3:
                task.log_info(
                    "连续3次点击再次观测后pt与词条均无变化，判定赛季货币不足或无法刷新，停止刷新直接进入"
                )
                task._season_observe_exhausted = True
                return False
        else:
            task._season_observe_unchanged_count = 0

    task._season_observe_last_sig = current_sig
    task._season_observe_clicked = True
    task.log_info("存储数据保存上限不足，点击再次观测")
    task.click_box(observe_boxes[0])
    task.sleep(1)
    return True


def handle_zero_system_initial_page(task: TriggerTask):
    """零式系统初始页面：存储数据价值不足时进入重新合成。"""
    title_text = _get_region_text(task, (0.076, 0.011, 0.291, 0.106))
    if _get_game_text(task, "零式系统") not in title_text:
        return False

    enter_text = _get_region_text(task, (0.681, 0.850, 0.988, 0.972))
    if "进入" not in enter_text:
        return False

    task.log_info("检测到零式系统初始页面")
    value_text = _get_region_text(task, (0.685, 0.317, 0.980, 0.825))
    value_match = _match_storage_data_value(task, value_text)
    required_level = int(
        _get_config_value(task, "存储数据保存上限大于多少", 120)
    )
    if value_match:
        data_value_level = int(value_match.group(1))
        task.log_info(
            f"零式系统当前存储数据保存上限={data_value_level}，"
            f"要求大于等于{required_level}"
        )
        if data_value_level >= required_level:
            return False
    else:
        task.log_info(f"零式系统未识别到存储数据保存上限，区域文本=「{value_text}」")

    task.log_info("存储数据保存上限未达要求，点击进入重新合成")
    _move_and_click(task, 0.968, 0.153)
    task.sleep(1)
    return True


def handle_disable_adaptation_distortion(task: TriggerTask):
    """刷空档时关闭已启用的适应畸变。"""
    if _get_config_value(task, "刷空档", False) is not True:
        return False

    page_text = _get_region_text(task, (0.480, 0.050, 0.573, 0.136))
    adaptation_text = _get_game_text(task, "适应畸变")
    if adaptation_text not in page_text:
        return False

    relative_x, relative_y = 0.575, 0.093
    pixel_x = min(task.width - 1, max(0, round(relative_x * task.width)))
    pixel_y = min(task.height - 1, max(0, round(relative_y * task.height)))
    blue, green, red = (
        int(value) for value in task.frame[pixel_y, pixel_x, :3]
    )
    rgb = (red, green, blue)
    target_rgb = (255, 186, 55)
    color_matches = max(
        abs(actual - target)
        for actual, target in zip(rgb, target_rgb)
    ) <= 35
    task.log_info(
        f"适应畸变开关颜色RGB={rgb}，"
        f"是否接近{target_rgb}={color_matches}"
    )
    if not color_matches:
        return False

    task.log_info("刷空档检测到适应畸变已开启，点击关闭")
    _move_and_click(task, relative_x, relative_y)
    task.sleep(1)
    return False


def _save_runtime_feature(task: TriggerTask, feature_name: str, region, target_region=None):
    """将当前帧指定区域保存为运行时特征，可按目标区域尺寸缩放。"""
    import os
    import cv2
    from ok.feature.Box import Box
    from ok.feature.Feature import Feature
    from ok.util.config import Config
    from ok.util.file import get_relative_path

    x1, y1, x2, y2 = region
    left = round(x1 * task.width)
    top = round(y1 * task.height)
    right = round(x2 * task.width)
    bottom = round(y2 * task.height)
    feature_mat = task.frame[top:bottom, left:right, :3].copy()
    if feature_mat.size == 0:
        task.log_error(f"保存特征「{feature_name}」失败：截图区域为空")
        return False

    if target_region is not None:
        target_x1, target_y1, target_x2, target_y2 = target_region
        left = round(target_x1 * task.width)
        top = round(target_y1 * task.height)
        right = round(target_x2 * task.width)
        bottom = round(target_y2 * task.height)
        feature_mat = cv2.resize(
            feature_mat,
            (right - left, bottom - top),
            interpolation=cv2.INTER_AREA,
        )

    feature_set = task.executor.feature_set
    with feature_set.lock:
        feature_set.feature_dict[feature_name] = Feature(feature_mat, left, top)
        feature_set.box_dict[feature_name] = Box(
            left, top, right - left, bottom - top, 1.0, feature_name
        )

    config_folder = get_relative_path(Config.config_folder)
    os.makedirs(config_folder, exist_ok=True)
    feature_path = os.path.join(config_folder, f"{feature_name}.png")
    if cv2.imwrite(feature_path, feature_mat):
        task.log_info(
            f"已将主战员头像保存为特征「{feature_name}」：{feature_path}"
        )
    else:
        task.log_info(f"保存特征图片失败：{feature_path}")
    return True


def _sync_target_member_engraving_from_archive(task: TriggerTask, member_index: int):
    """在战斗员信息页面同步目标主战员当前已装备的刻印词条（仅刻印刷取开启时生效）。"""
    if not _is_engraving_farm_enabled(task):
        return

    equipment = _equipment_state(task)
    eng_priority = _engraving_priority(task)

    for slot in range(3):
        base_x = 0.145 + member_index * 0.273 + slot * 0.078
        slot_roi = (base_x, 0.835, base_x + 0.080, 0.920)
        slot_eng_type, slot_score, _ = _detect_engraving_icon(
            task, slot_roi, base_scales=(0.55, 0.60, 0.65), threshold=0.75
        )
        if not slot_eng_type:
            continue

        task.log_info(
            f"战斗员界面: 第{member_index + 1}号主战员第{slot + 1}号装备槽检测到{slot_eng_type}刻印(置信度={slot_score:.3f})，点击查看词条"
        )
        _move_and_click(task, base_x + 0.040, 0.895)
        task.sleep(0.8)
        task.next_frame()

        title_type, _, title_center = _detect_engraving_icon(
            task, (0.15, 0.30, 0.90, 0.50), base_scales=(0.58, 0.65, 0.72), threshold=0.75
        )
        _, _, desc_center = _detect_engraving_icon(
            task, (0.15, 0.42, 0.85, 0.70), base_scales=(0.48, 0.533, 0.59), threshold=0.75
        )
        if desc_center is None and title_center is not None:
            tri_roi = (
                max(0.0, title_center[0] - 0.15),
                min(1.0, title_center[1] + 0.10),
                min(1.0, title_center[0] + 0.25),
                min(1.0, title_center[1] + 0.32),
            )
            for _ in range(5):
                _, tri_center = _match_engraving_template(
                    task, "engraving_scroll_down.png", tri_roi, (0.58, 0.65, 0.72), 0.80
                )
                if tri_center is None:
                    break
                _move_and_click(task, tri_center[0], tri_center[1])
                task.sleep(0.6)
                task.next_frame()
                _, _, desc_center = _detect_engraving_icon(
                    task, (0.15, 0.42, 0.85, 0.70), base_scales=(0.48, 0.533, 0.59), threshold=0.75
                )
                if desc_center is not None:
                    break

        task.all_texts = _simplify_texts(task.ocr())
        if desc_center is not None:
            desc_region = (
                max(0.0, desc_center[0] - 0.02),
                max(0.0, desc_center[1] - 0.025),
                min(1.0, desc_center[0] + 0.38),
                min(1.0, desc_center[1] + 0.18),
            )
        elif title_center is not None:
            desc_region = (
                max(0.0, title_center[0] - 0.16),
                min(1.0, title_center[1] + 0.06),
                min(1.0, title_center[0] + 0.28),
                min(1.0, title_center[1] + 0.28),
            )
        else:
            desc_region = (0.15, 0.42, 0.85, 0.72)

        engraving_text = _extract_engraving_description(task, desc_region, desc_center)
        eng_kw, eng_rank = _match_engraving_text(engraving_text, eng_priority)
        record = {
            "type": title_type or slot_eng_type,
            "text": engraving_text,
            "rank": eng_rank,
        }
        task.log_info(
            f"战斗员界面同步刻印: 槽位={slot + 1}，词条=「{engraving_text}」，"
            f"匹配配置={f'「{eng_kw}」(优先级={eng_rank + 1})' if eng_kw else '未命中'}"
        )
        equipment["engravings"][slot] = record

        # 点击弹窗外上方空白区域返回战斗员界面
        _move_and_click(task, 0.500, 0.150)
        task.sleep(0.6)
        task.next_frame()

    task.log_info(f"刻印刷取: 启动时已同步目标主战员各槽位刻印={equipment['engravings']}")
    task._last_change_time = time.time()


def handle_archive_target_member(task: TriggerTask):
    """信息统计页面：按配置记录刷存档时使用的目标主战员特征。"""
    search_box = task.box_of_screen(0.005, 0.018, 0.080, 0.343)
    member_info = task.find_one(
        feature_name=["memberinfo", "memberinfo2"], box=search_box
    )
    if not member_info:
        return False

    task.log_info(
        f"检测到信息统计页面，点击「{member_info.name}」，相似度={member_info.confidence:.4f}"
    )
    task.click_box(member_info)
    task.sleep(0.5)
    _move_and_click(task, 0.201, 0.056)
    task.sleep(0.5)

    target_name = _get_config_value(task, "刷存档主战员", "海德玛丽")
    if not target_name:
        task.log_info("未配置刷存档主战员，关闭信息统计页面")
        _move_and_click(task, 0.960, 0.054)
        task.sleep(1)
        return True

    member_positions = [(0.159, 0.368), (0.432, 0.368), (0.705, 0.369)]
    member_regions = [
        (0.233, 0.151, 0.301, 0.269),
        (0.502, 0.151, 0.570, 0.269),
        (0.780, 0.151, 0.848, 0.269),
    ]
    task.all_texts = _simplify_texts(task.ocr())
    member_names = []
    for x, y in member_positions:
        name_box = find_box_at_point(task, x, y)
        member_names.append(name_box.name.strip() if name_box else "")
    task.log_info(f"信息统计页面主战员：{member_names}")

    for index, member_name in enumerate(member_names):
        if member_name and (target_name in member_name or member_name in target_name):
            if _save_runtime_feature(task, "target_member", member_regions[index]):
                _save_runtime_feature(
                    task,
                    "target_member_small",
                    member_regions[index],
                    target_region=(0.534, 0.225, 0.587125, 0.316667),
                )
                _save_runtime_feature(
                    task,
                    "target_member_in_select_card",
                    member_regions[index],
                    target_region=(
                        0.117708333,
                        0.178703704,
                        0.175520833,
                        0.278703704,
                    ),
                )
                _save_runtime_feature(
                    task,
                    "target_member_tiny",
                    member_regions[index],
                    target_region=(
                        0.65790625,
                        0.470962963,
                        0.70009375,
                        0.545037037,
                    ),
                )
                _save_runtime_feature(
                    task,
                    "target_member_in_mask_card",
                    member_regions[index],
                    target_region=(
                        0.663635417,
                        0.481148148,
                        0.694364583,
                        0.534851852,
                    ),
                )
                _save_runtime_feature(
                    task,
                    "target_member_large",
                    member_regions[index],
                    target_region=(0.218, 0.320, 0.28675, 0.439444444),
                )
                task.log_info(
                    f"第{index + 1}个主战员「{member_name}」命中刷存档主战员「{target_name}」"
                )
            _sync_target_member_engraving_from_archive(task, index)
            task.node_status["save_target_member"] = True
            _move_and_click(task, 0.960, 0.054)
            task.sleep(1)
            return True

    task.log_info(f"三个主战员均未命中刷存档主战员「{target_name}」")
    _move_and_click(task, 0.960, 0.054)
    task.node_status["save_target_member"] = True
    task.sleep(1)
    return True


def handle_save_target_member(task: TriggerTask):
    """主界面：进入信息统计页面获取刷存档目标主战员头像特征。"""
    if not _get_current_hp_percent(task):
        return False

    target_name = _get_config_value(task, "刷存档主战员", "海德玛丽")
    if not target_name:
        return False
    if task.node_status.get("save_target_member", False):
        return False

    task.log_info("前往获取刷存档主战员头像特征")
    _move_and_click(task, 0.182, 0.081)
    task.sleep(2)
    return True

def handle_battle_auto_check(task: TriggerTask):
    """战斗页面: 检测手牌数并检查自动战斗是否开启，如关闭则开启。"""
    box = find_box_at_point(task, 0.512, 0.969)
    if not (box and re.search(r'\d+/10', box.name)):
        return False

    attack_box = task.find_one(
        feature_name="start_attack_event",
        box=task.box_of_screen(0.394, 0.779, 0.600, 0.858),
    )
    if attack_box:
        task.log_info(
            f"战斗页面检测到start_attack_event特征，"
            f"相似度={attack_box.confidence:.4f}，点击发起攻击"
        )
        task.click_box(attack_box)
        task.sleep(1)
        return True

    from ok.feature.Box import Box
    from ok.util.color import calculate_color_percentage
    auto_box = Box(
        x=int(0.877 * task.width),
        y=int(0.050 * task.height),
        width=int(4),
        height=int(4)
    )
    white_ratio = calculate_color_percentage(
        task.frame,
        {'r': (255, 255), 'g': (255, 255), 'b': (255, 255)},
        box=auto_box
    )
    task.log_info(f"自动战斗按钮区域白色占比: {white_ratio:.2%}")
    if white_ratio > 0.02:
        task.log_info("自动战斗处于关闭状态，点击开启")
        _move_and_click(task, 0.880, 0.056)
        task.sleep(0.5)

    # 如果已到达最终boss节点，标记boss战状态
    if hasattr(task, 'node_status') and task.node_status.get('reach_final_boss', False):
        task.node_status['final_boss_battle'] = True
        task.log_info("检测到最终boss战斗开始，final_boss_battle=True")
    return True


def handle_discovery_select(task: TriggerTask): #忘了按个页面要用
    """发现选择页面：标题区域内出现「获得法典」文本即为该页面，选择达到配置层级的存储数据，否则取消。"""
    title_text = _get_region_text(task, (0.313, 0.010, 0.670, 0.193))
    if "获得法典" not in title_text:
        return False

    task.log_info(f"检测到发现选择页面，标题区域文本=「{title_text}」")
    required_level = int(
        _get_config_value(task, "存储数据保存上限大于多少", 120)
    )
    option_regions = [
        (0.058, 0.358, 0.315, 0.800),
        (0.370, 0.356, 0.629, 0.796),
        (0.682, 0.356, 0.940, 0.796),
    ]
    for index, region in enumerate(option_regions):
        option_text = _get_region_text(task, region)
        level_match = _match_storage_data_value(task, option_text)
        if not level_match:
            task.log_info(
                f"发现选项{index + 1}未识别到存储数据保存上限，"
                f"区域文本=「{option_text}」"
            )
            continue

        data_value_level = int(level_match.group(1))
        task.log_info(
            f"发现选项{index + 1}存储数据保存上限={data_value_level}，"
            f"要求大于等于{required_level}"
        )
        if data_value_level < required_level:
            continue

        click_x = (region[0] + region[2]) / 2
        click_y = (region[1] + region[3]) / 2
        task.log_info(f"发现选项{index + 1}满足保存上限要求，点击该选项")
        _move_and_click(task, click_x, click_y)
        task.sleep(1)
        return True

    task.log_info("没有发现选项满足存储数据保存上限要求，点击取消")
    _move_and_click(task, 0.961, 0.050)
    task.sleep(1)
    return True


def handle_zero_system_home(task: TriggerTask):
    """零式系统首页: 点击法典。"""
    title = find_box_at_point(task, 0.120, 0.046)
    codex = find_box_at_point(task, 0.812, 0.469)
    if title and _get_game_text(task, '零式系统') in title.name and codex and codex.name == "法典":
        task.log_info("检测到零式系统首页，点击法典")
        task.click_box(codex)
        task.sleep(2)
        return True
    return False


def handle_codex_search(task: TriggerTask):
    """法典搜索页面: 点击搜索新坐标。"""
    title = find_box_at_point(task, 0.5, 0.438)
    if not (title and title.name == "法典"):
        return False
    task.log_info("检测到法典搜索页面，点击搜索新坐标")
    _move_and_click(task, 0.5, 0.760)
    task.sleep(2)
    return True


def handle_memory_elimination(task: TriggerTask):
    """记忆消除页面: 点击记忆消除按钮。"""
    box = find_box_at_point(task, 0.589, 0.703)
    if box and _get_game_text(task, '记忆消除') in box.name:
        task.log_info("检测到记忆消除页面，点击记忆消除")
        task.click_box(box)
        task.sleep(0.5)
        return True
    return False


def handle_chaos_craft(task: TriggerTask):
    """卡厄思合成页面: 检测"卡厄思合成"(0.774,0.925)或"免费合成"(0.563,0.922)按钮，点击并等待。"""
    box = find_box_at_point(task, 0.774, 0.925)
    if box and "卡厄思合成" in box.name:
        task.log_info(f"检测到卡厄思合成页面，点击「{box.name}」")
        task.click_box(box)
        task.sleep(2)
        return True
    box = find_box_at_point(task, 0.563, 0.922)
    if box and "免费合成" in box.name:
        task.log_info(f"检测到卡厄思合成页面，点击「{box.name}」")
        task.click_box(box)
        task.sleep(2)
        return True
    return False


def handle_conquer_difficulty(task: TriggerTask):
    """征服新难度页面: 检测到'征服新难度'则点击空白处关闭。"""
    box = find_box_at_point(task, 0.502, 0.572)
    if box and "征服新难度" in box.name:
        task.log_info("检测到征服新难度页面，点击关闭")
        _move_and_click(task, 0.502, 0.943)
        task.sleep(1)
        return True
    return False


# ------------------------- 卡厄思模式独有页面处理函数（续） -------------------------

def handle_chaos_mask_engraving(task: TriggerTask):
    """面具卡牌刻印获取页面: 如果0.499,0.126处文本包含"面具卡牌刻印"，则为该页面。
    如果0.921,0.931处_clean_match"确认"后，检测0.495,0.221处是否包含"替换"：
      - 有"替换"（A逻辑）：点击刻印1，获取刻印1描述；命中配置则点击刻印2再判断，
        未命中则检查新刻印描述或刷新/跳过。
      - 无"替换"（原逻辑）：直接检查刻印描述，命中则return False，否则刷新或跳过。"""
    title_box = find_box_at_point(task, 0.499, 0.126)
    if not (title_box and "面具卡牌刻印" in title_box.name):
        return False

    task.log_info("检测到面具卡牌刻印获取页面")

    # 检查确认按钮是否可用
    confirm_box = find_box_at_point(task, 0.921, 0.931)
    if not (confirm_box and _clean_match(confirm_box.name, "确认")):
        return False

    specify_text = _get_config_value(task, '面具卡牌刻印', "自身攻击卡牌伤害总量提升30%")
    new_desc_region = (0.589, 0.601, 0.902, 0.762)
    slot_desc_region = (0.589, 0.336, 0.898, 0.487)

    # 检测是否处于替换模式
    replace_box = find_box_at_point(task, 0.495, 0.221)
    if replace_box and _get_game_text(task, "替换") in replace_box.name:
        task.log_info("检测到替换模式（A逻辑）")

        # ===== A逻辑：刻印1 =====
        task.log_info("点击刻印1")
        _move_and_click(task, 0.399, 0.472)
        task.sleep(0.5)

        slot_desc = _get_region_text(task, slot_desc_region)
        task.log_info(f"刻印1描述: {slot_desc}")

        if specify_text not in slot_desc:
            # 刻印1未命中，检查新刻印
            new_desc = _get_region_text(task, new_desc_region)
            task.log_info(f"新刻印描述: {new_desc}")
            if specify_text in new_desc:
                task.log_info(f"新刻印命中「{specify_text}」，交给确认按钮")
                return False
            # 检查刷新
            refresh_box = find_box_at_point(task, 0.916, 0.810)
            if refresh_box:
                match = re.search(r'(\d+)/3', refresh_box.name)
                if match:
                    remaining = int(match.group(1))
                    task.log_info(f"刻印1未命中，剩余刷新次数: {remaining}")
                    if remaining > 0:
                        task.log_info(f"点击刷新")
                        _move_and_click(task, 0.916, 0.810)
                        task.sleep(1)
                        return True
            # 无法刷新，点击跳过
            task.log_info("无法刷新，点击跳过")
            _move_and_click(task, 0.747, 0.932)
            task.sleep(1)
            return True

        # ===== 刻印1命中，继续刻印2 =====
        task.log_info("刻印1命中，点击刻印2")
        _move_and_click(task, 0.399, 0.610)
        task.sleep(0.5)

        slot2_desc = _get_region_text(task, slot_desc_region)
        task.log_info(f"刻印2描述: {slot2_desc}")

        if specify_text in slot2_desc:
            # 刻印2也命中，点击跳过
            task.log_info("刻印2也命中配置，点击跳过")
            _move_and_click(task, 0.747, 0.932)
            task.sleep(1)
            return True

        # 刻印2未命中，检查新刻印
        new_desc = _get_region_text(task, new_desc_region)
        task.log_info(f"新刻印描述: {new_desc}")
        if specify_text in new_desc:
            task.log_info(f"新刻印命中「{specify_text}」，交给确认按钮")
            return False

        # 检查刷新
        refresh_box = find_box_at_point(task, 0.916, 0.810)
        if refresh_box:
            match = re.search(r'(\d+)/3', refresh_box.name)
            if match:
                remaining = int(match.group(1))
                task.log_info(f"刻印2未命中，剩余刷新次数: {remaining}")
                if remaining > 0:
                    task.log_info(f"点击刷新")
                    _move_and_click(task, 0.916, 0.810)
                    task.sleep(1)
                    return True

        # 无法刷新，点击跳过
        task.log_info("无法刷新，点击跳过")
        _move_and_click(task, 0.747, 0.932)
        task.sleep(1)
        return True

    # ===== 原逻辑：无替换模式 =====
    task.log_info("无替换模式，执行原逻辑")
    desc_text = _get_region_text(task, (0.583, 0.463, 0.937, 0.621))
    task.log_info(f"刻印描述: {desc_text}")

    if specify_text in desc_text:
        task.log_info(f"刻印描述包含「{specify_text}」，交给确认按钮处理")
        return False

    # 未命中，检查可刷新次数
    refresh_box = find_box_at_point(task, 0.913, 0.667)
    if refresh_box:
        match = re.search(r'(\d+)/3', refresh_box.name)
        if match:
            remaining = int(match.group(1))
            task.log_info(f"未命中指定刻印，剩余刷新次数: {remaining}")
            if remaining > 0:
                task.log_info(f"剩余刷新次数{remaining}>0，点击刷新")
                _move_and_click(task, 0.913, 0.667)
                task.sleep(1)
                return True

    task.log_info("无可刷新次数，跳过")
    return False


def _click_mask_card_skip(task: TriggerTask):
    """点击面具卡牌页面右下角跳过按钮（优先匹配文本，否则点击 >| 图标固定位置）。"""
    skip_box = find_text(task, r'跳过')
    if skip_box:
        task.click_box(skip_box)
    else:
        _move_and_click(task, 0.762, 0.931)
    task._last_change_time = time.time()
    task.sleep(0.5)


def handle_mask_card(task: TriggerTask):
    """面具获得卡牌页面: 根据0.507,0.090处的面具获得提示判断页面。
    检测0.120,0.228,0.945,0.418范围内是否有三个"人格面具"文本，
    如果不足三个则说明已选择过人格面具，点击跳过。
    否则提取三张卡牌描述区域文本，匹配配置中"指定面具卡牌"内容。
    匹配成功则点击对应卡牌，否则刷新或跳过。"""
    box = find_box_at_point(task, 0.507, 0.090)
    is_mask_card_page = (
        box
        and "面具" in box.name
        and "获得" in box.name
        and "卡牌" in box.name
    )
    if not is_mask_card_page:
        return False

    task.log_info("检测到面具卡牌获得页面")
    specify_text = _get_config_value(task, '指定面具卡牌', "丢弃最多2张卡牌")
    specify_text = specify_text.strip() if isinstance(specify_text, str) else ""
    if not specify_text:
        task.log_info("指定面具卡牌配置为空，直接点击跳过")
        _click_mask_card_skip(task)
        return True

    cards = recognize_cards(task, page="人格面具卡牌获得页面")
    mask_cards = [card for card in cards if "人格面具" in card["name"]]
    for _ in range(2):
        if len(mask_cards) >= 3:
            break
        task.log_info(f"当前仅识别到{len(mask_cards)}张人格面具卡牌，等待动画结束后重试识别")
        task.sleep(0.8)
        task.all_texts = _simplify_texts(task.ocr())
        cards = recognize_cards(task, page="人格面具卡牌获得页面")
        mask_cards = [card for card in cards if "人格面具" in card["name"]]
    if len(mask_cards) < 3:
        task.log_info("已选择过人格面具，点击跳过")
        _click_mask_card_skip(task)
        return True

    task.log_info("检测到3张人格面具卡牌")

    mask_position = task.node_status.get("target_mask_card_position", -1)
    if mask_position == -1:
        target_region = task.box_of_screen(0.006, 0.010, 0.081, 0.131)
        for index, card in enumerate(mask_cards):
            task.log_info(
                f"人格面具卡牌归属检测: 长按从左到右第{index + 1}张卡牌"
            )
            click_x = int(card["x"] * task.width)
            click_y = int(card["y"] * task.height)
            task.move_relative(card["x"], card["y"])
            task.mouse_down(click_x, click_y, key="left")
            task.sleep(2)
            task.mouse_up(key="left")
            task.sleep(1)

            target_member = task.find_one(
                feature_name="target_member_in_mask_card",
                box=target_region,
                threshold=0.6,
            ) if task.feature_exists("target_member_in_mask_card") else None
            if target_member:
                task.node_status["target_mask_card_position"] = index
                mask_position = index
                task.log_info(
                    f"人格面具卡牌归属检测: 第{index + 1}张属于目标主战员，"
                    f"相似度={target_member.confidence:.4f}"
                )
            else:
                task.log_info(
                    f"人格面具卡牌归属检测: 第{index + 1}张不属于目标主战员"
                )

            task.log_info("人格面具卡牌详情页面触发关闭事件，点击固定关闭位置")
            _move_and_click(task, 0.513, 0.931)
            task.sleep(2)
            if target_member:
                break
        task._last_change_time = time.time()

    if not 0 <= mask_position < len(mask_cards):
        task.log_info("未识别到目标主战员的人格面具卡牌，默认启用第一张")
        mask_position = 0
    enabled_mask_cards = [mask_cards[mask_position]]
    task.log_info(f"本次启用从左到右第{mask_position + 1}张人格面具卡牌")

    for card in enabled_mask_cards:
        desc_text = card["description"]
        task.log_info(f"卡牌{mask_position + 1}描述: {desc_text}")
        if is_subsequence(specify_text, desc_text):
            task.log_info(
                f"卡牌{mask_position + 1}描述子序列命中「{specify_text}」，点击该卡牌"
            )
            _move_and_click(task, card["x"], card["y"])
            task.sleep(0.5)
            return True

    # 未匹配到指定卡牌，检查左下角刷新按钮区域的剩余刷新次数（如 3/3）
    refresh_boxes = [
        b for b in sorted(task.all_texts, key=lambda item: item.x)
        if 0.120 <= (b.x + b.width / 2) / task.width <= 0.340
        and 0.890 <= (b.y + b.height / 2) / task.height <= 0.965
        and b.name.strip()
    ]
    refresh_text = "".join(b.name.strip() for b in refresh_boxes)
    match = re.search(r'(\d+)\s*[/／]\s*3', refresh_text)
    if match:
        remaining = int(match.group(1))
        task.log_info(f"未匹配到指定面具卡牌，刷新区域OCR=「{refresh_text}」，剩余刷新次数: {remaining}")
        if remaining > 0:
            task.log_info(f"剩余刷新次数{remaining}>0，点击刷新")
            _move_and_click(task, 0.220, 0.931)
            task._last_change_time = time.time()
            task.sleep(2.5)
            return True

    task.log_info("无刷新次数或无需刷新，点击跳过")
    _click_mask_card_skip(task)
    return True


def _archive_value_at(task: TriggerTask, center_x, center_y):
    """读取垃圾桶左侧的存档价值(TB)，读不到返回 None。"""
    value_box = find_box_at_point(task, center_x - 0.107, center_y - 0.025)
    if not value_box:
        return None
    value_match = re.search(r'\d+', value_box.name.replace(',', ''))
    return int(value_match.group()) if value_match else None


def handle_data_collected(task: TriggerTask):
    """存储数据收集完成页面：低于阈值的存档点垃圾桶，弹确认就交给通用确认处理。"""
    node_status = getattr(task, 'node_status', None)
    box = find_box_at_point(task, 0.505, 0.111)
    if not (box and _get_game_text(task, '存储数据收集完成') in box.name):
        # 离开页面时清理点击记录，避免影响下一次
        if node_status is not None:
            node_status.pop('storage_delete_clicked', None)
        task._force_delete_archive_no_engraving = False
        return False

    force_delete = bool(getattr(task, '_force_delete_archive_no_engraving', False))
    retain_threshold = _get_config_value(
        task, '保留大于多少TB的存档', 62000
    )
    if retain_threshold <= 0 and not force_delete:
        task.log_info("保留大于多少TB的存档设置为0，保留全部存档")
        return False
    if node_status is None:
        return False

    # 二次确认弹窗已经出现时不再点垃圾桶，交给通用确认按钮处理
    if any(
        "确认" in text_box.name or "确定" in text_box.name
        for text_box in task.all_texts
    ):
        return False

    # 刚点过垃圾桶，等一帧确认结果，避免同一槽位被连续点击
    last_click = node_status.get('storage_delete_clicked')
    if last_click and time.time() - last_click < 1:
        return True

    for feature_name in ["deletecards", "deletecards2", "deletecards3"]:
        features = task.find_feature(
            feature_name=feature_name,
            horizontal_variance=0.005,
            vertical_variance=0.005,
        ) or []
        for feature in features:
            feature_center_x = (feature.x + feature.width / 2) / task.width
            feature_center_y = (feature.y + feature.height / 2) / task.height
            if force_delete:
                task.log_info(
                    f"首层未刷到目标刻印重开，无论TB多少直接强制删除存档({feature_name})"
                )
                task.click_box(feature)
                node_status['storage_delete_clicked'] = time.time()
                return True
            archive_value = _archive_value_at(task, feature_center_x, feature_center_y)
            if archive_value is None:
                # 读不到价值时不删除，避免误删高价值存档
                task.log_info(f"{feature_name}未识别到存档价值，跳过删除以避免误删")
                continue
            if archive_value > retain_threshold:
                task.log_info(
                    f"{feature_name}对应存档价值{archive_value}TB高于保留阈值"
                    f"{retain_threshold}TB，跳过删除"
                )
                continue
            task.log_info(
                f"{feature_name}对应存档价值{archive_value}TB不高于阈值"
                f"{retain_threshold}TB，点击垃圾桶"
            )
            task.click_box(feature)
            node_status['storage_delete_clicked'] = time.time()
            return True
    task.log_info("检测到存储数据收集完成，由通用按钮处理")
    return False


def handle_stage_end_data_details(task: TriggerTask):
    """关卡结束数据详情页面：检测到存储数据后关闭详情。"""
    page_text = _get_region_text(task, (0.111, 0.103, 0.338, 0.243))
    if _get_game_text(task, "存储数据") not in page_text:
        return False

    task.log_info("检测到关卡结束数据详情页面，点击关闭")
    _move_and_click(task, 0.883, 0.156)
    task.sleep(1)
    return True


# def handle_cares_tip(task: TriggerTask):
#     """卡厄思 TIP 提示页面: 点击关闭。"""
#     box = find_box_at_point(task, 0.502, 0.286)
#     if box and box.name == "TIP":
#         _move_and_click(task, 0.884, 0.915)
#         return True
#     return False


def handle_expedition_unlock(task: TriggerTask):
    """解锁探险记录页面: 点击确定。"""
    box = find_box_at_point(task, 0.5, 0.151)
    if box and _get_game_text(task, '解锁的探险记录') in box.name:
        task.log_info("检测到解锁探险记录页面，点击页面")
        _move_and_click(task, 0.5, 0.95)
        task.sleep(1)
        return True
    return False


# ------------------------- 精神崩溃/创伤中心（卡厄思模式特有） -------------------------

def handle_mental_breakdown(task: TriggerTask):
    """精神崩溃发生页面: 根据配置决定是否治疗崩溃。"""
    box = find_box_at_point(task, 0.496, 0.186)
    if box and _get_game_text(task, '精神崩溃发生') in box.name:
        if _get_config_value(task, '治疗崩溃', True):
            task.log_info("检测到精神崩溃发生，去创伤中心治疗")
            _move_and_click(task, 0.706, 0.915)
            task.sleep(1)
            return True
    return False


def handle_trauma_center(task: TriggerTask):
    """创伤中心: 优先使用旅行券治疗；若配置"优先使用金币治疗"为True，则始终使用金币治疗。"""
    box = find_box_at_point(task, 0.125, 0.049)
    if not (box and _get_game_text(task, '创伤中心') in box.name):
        return False
    task.log_info("检测到创伤中心，采取策略，优先使用旅行券")
    if find_text(task, _get_game_text(task, '没有恢复中的战员')):
        _move_and_click(task, 0.044, 0.046)
        return True
    _move_and_click(task, 0.420, 0.339)
    task.sleep(0.5)
    travel_ticket = task.ocr(0.933, 0.904, 0.971, 0.943)
    if travel_ticket:
        has_ticket = int(travel_ticket[0].name[0]) > 0
        prefer_gold = _get_config_value(task, '优先使用金币治疗', False)
        if prefer_gold:
            task.log_info("优先使用金币治疗配置为True，点击金币治疗")
            _move_and_click(task, 0.702, 0.924)
        else:
            _move_and_click(task, 0.798 if has_ticket else 0.702, 0.924)
        task.sleep(0.5)
    return True


def handle_treating(task: TriggerTask):
    """治疗进行中页面: 选择治疗方法。"""
    if find_text(task, _get_game_text(task, '选择哪种方法进行治疗')):
        task.log_info("检测到治疗进行中")
        _move_and_click(task, 0.765, 0.500)
        return True
    return False


def handle_treat_approve(task: TriggerTask):
    """治疗完成页面: 点击批准。"""
    if find_text(task, _get_game_text(task, '点击批准')):
        task.log_info("检测到治疗完成，点击批准")
        _move_and_click(task, 0.768, 0.810)
        return True
    return False


def handle_go_to_chaos_core(task: TriggerTask):
    """前往卡厄思核心按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "前往卡厄思核心"):
        if is_button_active(task, box):
            task.log_info("检测到前往卡厄思核心按钮，点击进入")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("前往卡厄思核心按钮未激活（灰色），跳过点击")
            return False
    return False


def handle_go_to_memory_end(task: TriggerTask):
    """卡厄思结算页面右下角「前往记忆之末」按钮: 检测到后点击进入记忆之末。"""
    region = (0.740, 0.850, 0.995, 0.980)
    memory_end_text = _get_game_text(task, "记忆之末")
    box = next(
        (
            text_box
            for text_box in task.all_texts
            if region[0] <= (text_box.x + text_box.width / 2) / task.width <= region[2]
            and region[1] <= (text_box.y + text_box.height / 2) / task.height <= region[3]
            and memory_end_text in text_box.name
        ),
        None,
    )
    if box:
        task.log_info("检测到前往记忆之末按钮，点击进入")
        task.click_box(box)
        task.sleep(1)
        return True

    # OCR 可能把按钮文字拆成多个框，退回整块区域文本匹配
    region_text = _get_region_text(task, region).replace(" ", "")
    if memory_end_text not in region_text:
        return False

    task.log_info("检测到前往记忆之末按钮（区域文本匹配），点击进入")
    _move_and_click(task, 0.881, 0.908)
    task.sleep(1)
    return True


def _precision_button_active(task: TriggerTask, box):
    """精密加工记忆按钮是否可用: 采样按钮内部上沿背景，避开文字、图标及左侧光效。"""
    height, width = task.frame.shape[:2]
    patch = task.frame[int(height * 0.763):int(height * 0.771),
                       int(width * 0.770):int(width * 0.850), :3]
    if patch.size == 0:
        return False
    blue, _, red = patch.mean(axis=(0, 1))
    return (red - blue) > 30


def handle_precision_memory_process(task: TriggerTask):
    """记忆之末「精密加工记忆（记忆雕琢）」页面: 开启加工记忆时先转换词条，再点击右侧雕琢强化。"""
    title_text = _get_region_text(task, (0.400, 0.080, 0.600, 0.170)).replace(" ", "")
    precision_memory_text = _get_game_text(task, "精密加工记忆")
    if precision_memory_text not in title_text and "精密加工" not in title_text and "记忆雕琢" not in title_text:
        return False

    cards = recognize_cards(
        task, region=(0.366, 0.233, 0.639, 0.500), page="精密加工记忆页面"
    )

    # 记录已进入过该页面，避免事件对话反复选择「精密加工记忆」造成死循环
    status = getattr(task, "node_status", None)
    if isinstance(status, dict):
        status["precision_memory_visited"] = True

    enable_process = _get_config_value(task, "加工记忆", False) is True
    keywords = _get_memory_process_keywords(task)
    already_processed = isinstance(status, dict) and status.get("memory_process_done", False)

    if enable_process and keywords and not already_processed:
        matched_kw = None
        for card in cards:
            matched_kw = _card_matches_memory_keywords(card, keywords)
            if matched_kw:
                break
        if matched_kw:
            task.log_info(
                f"当前记忆卡牌已命中加工记忆词条「{matched_kw}」，无需记忆加工，直接进行记忆雕琢"
            )
            if isinstance(status, dict):
                status["memory_process_done"] = True
        else:
            process_keywords = {"加工记忆", "记忆加工", _get_game_text(task, "加工记忆")}
            process_box = next(
                (
                    box for box in task.all_texts
                    if 0.020 <= (box.x + box.width / 2) / task.width <= 0.315
                    and 0.708 <= (box.y + box.height / 2) / task.height <= 0.867
                    and any(kw in box.name for kw in process_keywords if kw)
                ),
                None,
            )
            if process_box and _precision_button_active(task, process_box):
                task.log_info("当前卡牌未命中加工记忆词条，点击左侧「记忆加工」转换词条")
                if isinstance(status, dict):
                    status["memory_process_done"] = True
                _move_and_click(
                    task,
                    (process_box.x + process_box.width / 2) / task.width,
                    (process_box.y + process_box.height / 2) / task.height,
                )
                task.sleep(1.5)
                return True

    region = (0.700, 0.730, 0.995, 0.870)
    done_box = next(
        (
            text_box
            for text_box in task.all_texts
            if region[0] <= (text_box.x + text_box.width / 2) / task.width <= region[2]
            and region[1] <= (text_box.y + text_box.height / 2) / task.height <= region[3]
            and "完成" in text_box.name
        ),
        None,
    )
    if done_box:
        task.log_info(f"精密加工记忆已完成（按钮「{done_box.name}」），跳过点击并交由离开按钮退出")
        return False

    box = next(
        (
            text_box
            for text_box in task.all_texts
            if region[0] <= (text_box.x + text_box.width / 2) / task.width <= region[2]
            and region[1] <= (text_box.y + text_box.height / 2) / task.height <= region[3]
            and precision_memory_text in text_box.name
        ),
        None,
    )
    if not box:
        return False
    if not _precision_button_active(task, box):
        task.log_info("精密加工记忆按钮已变灰（材料耗尽），跳过点击")
        return False

    task.log_info("检测到精密加工记忆按钮，点击精密加工")
    task.click_box(box)
    task.sleep(1)
    return True


def handle_chaos_reward_claim(task: TriggerTask):
    """卡厄思模式奖励领取页面: 如果0.568,0.711处文本为"获得"且0.352,0.708处包含"取消"，则为奖励领取页面。
    识别0.959,0.281处"\\d/\\d"作为当前/最大战利品验证卡，
    如果验证卡大于0则点击获得，否则重置"领取奖励(只使用验证卡)"为False并取消。"""
    claim_box = find_box_at_point(task, 0.568, 0.711)
    cancel_box = find_box_at_point(task, 0.352, 0.708)
    if not (
        claim_box
        and _clean_match(claim_box.name, "获得")
        and cancel_box
        and "取消" in cancel_box.name
    ):
        return False

    task.log_info("检测到卡厄思模式奖励领取页面")

    # 读取0.959,0.281处的战利品验证卡文本，格式如 "2/3"
    verify_box = find_box_at_point(task, 0.959, 0.281)
    if verify_box and re.search(r'(\d+)/(\d+)', verify_box.name):
        match = re.search(r'(\d+)/(\d+)', verify_box.name)
        current_cards = int(match.group(1))
        max_cards = int(match.group(2))
        task.log_info(f"战利品验证卡: {current_cards}/{max_cards}")

        if current_cards > 0:
            task.log_info(f"当前战利品验证卡{current_cards}>0，点击获得")
            task.click_box(claim_box)
            task.sleep(1)
            return True
        else:
            task.log_info("当前战利品验证卡为0，将领取奖励(只使用验证卡)设置为False，点击取消")
            task.config['领取奖励(只使用验证卡)'] = False
            from ok.gui.Communicate import communicate
            communicate.task_list_updated.emit()
            _move_and_click(task, 0.352, 0.708)
            task.sleep(1)
            return True
    else:
        task.log_info("未检测到战利品验证卡信息，点击取消")
        _move_and_click(task, 0.352, 0.708)
        task.sleep(1)
        return True


def handle_chaos_reward_settlement(task: TriggerTask):
    """卡厄思奖励结算页面: 如果0.552,0.067处包含"结算"，则为卡厄思奖励结算页面。
    如果0.851,0.389处包含"获得"且当前战利品验证卡>0，则点击获得按钮。
    如果领取奖励关闭且只打第一层完成，则退出结算页面。"""
    title_box = find_box_at_point(task, 0.552, 0.067)
    if not (title_box and "结算" in title_box.name):
        return False

    task.log_info("检测到卡厄思奖励结算页面")

    if not _get_config_value(task, '领取奖励(只使用验证卡)', False):
        task.log_info("领取奖励(只使用验证卡)配置为False")
        return False if task.node_status.get('is_escaped', False) else _finish_only_first_layer(task)

    # 检查0.851,0.389处是否有"获得"按钮
    reward_box = find_box_at_point(task, 0.851, 0.389)
    if not (reward_box and "获得" in reward_box.name):
        task.log_info("未检测到获得按钮")
        return False if task.node_status.get('is_escaped', False) else _finish_only_first_layer(task)

    task.log_info("检测到获得按钮，点击获得")
    task.click_box(reward_box)
    task.sleep(1)
    return True


# 卡厄思模式 PAGE_HANDLERS
PAGE_HANDLERS = [
    handle_keyword_pause, #关键词暂停（最高优先级）
    handle_auto_stop,
    handle_save_target_member,
    handle_route_selection,
    # handle_stage_clear,
    log_credit,
    log_node_status,
    handle_flash_effect_no_card, #闪光效果页面卡牌未渲染，10秒后点最左卡牌兜底
    handle_stuck_log, #画面卡住检测及兜底处理
    handle_close_page, #点击屏幕关闭页面，优先于其他普通页面处理
    handle_event_crystal, #事件场景晶石收集物

    handle_refine_equipment_credit, #提炼装备信用点页面，优先于确认按钮
    handle_center_confirm, #页面中央确认按钮
    handle_archive_target_member, #信息统计页面，记录刷存档目标主战员
    handle_chaos_mask_engraving, #面具卡牌刻印获取页面
    handle_equipment, #装备选择
    handle_card_assign,
    handle_memory_process, #记忆加工三选一页面，优先于通用确认按钮
    handle_confirm, #确认按钮
    handle_mask_card, #面具卡牌获得页面
    handle_convert, #转换按钮
    handle_shop, #德朗商店
    handle_rest, #休息/商店入口
    handle_close_button, #关闭按钮
    handle_remove, #移除按钮
    handle_three_choice_card_remove, #三选一卡牌移除页面（低优先级兜底）
    handle_flash, #闪光按钮
    handle_reflash, #重新闪光按钮
    handle_grant_flash, #赋予闪光按钮
    handle_copy, #复制按钮
    handle_precision_memory_process, #记忆之末精密加工记忆，优先于离开按钮
    handle_leave, #离开按钮
    handle_mental_breakdown, #精神崩溃，优先级高于下一步按钮
    handle_data_collected, #存储数据收集完成，优先级高于下一步按钮
    # handle_battle_failed, #战斗失败，优先级高于下一步
    handle_expedition_result, #探险结果页面，优先级高于下一步
    handle_next_step, #下一步按钮
    handle_craft, #合成按钮
    handle_select, #选择按钮
    handle_go_to_chaos_core, #前往卡厄思核心
    handle_equipment_recast, #装备重铸按钮

    handle_minimizemap,
    handle_weakness_info,
    handle_non_battle_page,
    handle_battle_crash,
    handle_battle_auto_check,
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_card_reward,
    handle_memory_card_select,
    handle_meditation_card_select, #冥想选卡页：钉针优先
    handle_select_card,
    handle_copy_member,
    handle_copy_card_choice,
    handle_convert_card,
    handle_discovery_select,
    handle_negotiation,
    handle_chaos_reward_settlement, #卡厄思奖励结算页面，优先级高于继续按钮
    handle_chaos_reward_claim, #卡厄思模式奖励领取页面
    handle_go_to_memory_end, #卡厄思结算页面右下角「前往记忆之末」按钮
    handle_continue,
    handle_season_chaos_initial_page, #赛季卡厄思初始页面，优先于进入按钮
    handle_zero_system_initial_page, #零式系统初始页面，优先于进入按钮
    handle_disable_adaptation_distortion, #刷空档时关闭适应畸变，优先于进入按钮
    handle_enter,
    handle_obtain_reward,
    handle_view_original,
    handle_trauma_center,
    handle_treating,
    handle_treat_approve,
    handle_zero_system_home,
    handle_codex_search,
    handle_expedition_unlock,
    # handle_cares_tip,
    handle_memory_elimination,
    handle_chaos_craft,
    handle_conquer_difficulty,
    handle_escape,
    handle_pending_memory_escape,
    handle_skip,
    handle_event_task,
    handle_held_cards_page,
    handle_stage_end_data_details, #关卡结束数据详情页面，低优先级
]
