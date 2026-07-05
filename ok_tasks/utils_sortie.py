from ok import TriggerTask

from utils import (
    _simplify_texts, _get_config_value, _get_card_list, _get_route_priority,
    find_box_at_point, find_text, find_exact_text,
    _card_has_type_below, select_card, identify_node_type, calculate_dominant_hue,
    log_credit, handle_battle_crash, handle_close_page,
    handle_center_confirm, handle_settlement, handle_skip,
    handle_destiny_choice, handle_main_member_flash,
    handle_card_reward, handle_equipment, handle_mask_card,
    handle_remove_card, handle_copy_member, handle_copy_card,
    handle_flash_card, handle_copy_card_pick, handle_convert_card,
    handle_negotiation, handle_continue, handle_confirm, handle_enter,
    handle_event_task, handle_route_selection, handle_obtain_reward,
    handle_leave, handle_select, handle_rest, handle_view_original,
    handle_battle_failed, handle_data_collected, handle_mental_breakdown,
    handle_trauma_center, handle_explore_result, handle_treating,
    handle_treat_approve, handle_cares_tip, handle_close_button,
    handle_expedition_unlock, handle_card_assign, handle_non_battle_page,
    handle_remove, handle_flash, handle_reflash, handle_grant_flash, handle_copy, handle_equipment_recast, handle_weakness_info, handle_minimizemap,
    handle_held_cards_page, handle_unknown_page
)

import re
import random


# ------------------------- 出击模式独有工具 -------------------------

def _get_member_priority(task: TriggerTask):
    """读取主战员优先级配置，返回列表；解析失败使用默认顺序。"""
    value = _get_config_value(task, '主战员优先级', ["尼娅", "麦格纳", "米卡", "卡修斯"])
    return list(value) if isinstance(value, (list, tuple)) else ["尼娅", "麦格纳", "米卡", "卡修斯"]


def _get_blacklisted_members(task: TriggerTask):
    """读取拉黑主战员列表，返回列表；解析失败使用默认值。"""
    value = _get_config_value(task, '拉黑主战员', ["黛安娜", "阿黛尔海特"])
    return list(value) if isinstance(value, (list, tuple)) else ["黛安娜", "阿黛尔海特"]


def _get_battle_member_priority(task: TriggerTask):
    """读取出战主战员优先级配置，返回列表；解析失败使用默认顺序。"""
    value = _get_config_value(task, "出战主战员优先级", ["海德玛丽", "九", "力", "绯"])
    return list(value) if isinstance(value, (list, tuple)) else ["海德玛丽", "九", "力", "绯"]


def _card_key(text):
    table = str.maketrans("①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺❻❼❽❾❿⓵⓶⓷⓸⓹⓺⓻⓼⓽⓾０１２３４５６７８９",
                         "1234567890123456789012345678900123456789")
    text = text.translate(table)
    m = re.search(r"\d", text)
    return m.group(0) if m else None


def _hand_card_names(task: TriggerTask):
    """读取手牌区域内的卡牌名，排除按键和"攻击""强化""技能"。"""
    x1, y1, x2, y2 = 0.159, 0.683, 0.836, 0.831
    exclude_keywords = ["攻击", "强化", "技能"]
    boxes = [b for b in task.all_texts
             if x1 <= (b.x + b.width / 2) / task.width <= x2
             and y1 <= (b.y + b.height / 2) / task.height <= y2]
    return [b for b in boxes
            if not _card_key(b.name)
            and len(b.name) > 1
            and not any(kw in b.name for kw in exclude_keywords)]


def _hand_cards(task: TriggerTask):
    """识别手牌，返回按位置排序的卡牌名与按键列表，按键缺失时根据手牌数和间距推断。"""
    # 按键：包含数字的
    keys = [(b.x / task.width, b.y / task.height, _card_key(b.name)) for b in task.all_texts if _card_key(b.name)]
    keys.sort(key=lambda x: x[0])

    # 卡牌名
    card_names = _hand_card_names(task)
    card_names.sort(key=lambda b: b.x)

    # 读取手牌数
    hand_count = _read_hand_count(task)

    # 配对：每个卡牌匹配其左上方最近的未使用按键
    used_keys = set()
    cards = []
    for name_box in card_names:
        cx = name_box.x / task.width
        cy = name_box.y / task.height

        candidates = []
        for kx, ky, k in keys:
            if k in used_keys:
                continue
            # 垂直：按键在卡牌名上方 0.03~0.06
            if not (cy - 0.06 <= ky <= cy - 0.03):
                continue
            # 水平：按键在卡牌名左方，距离不超过 0.025
            if not (cx - 0.025 <= kx <= cx + 0.01):
                continue
            candidates.append((kx, ky, k))

        if candidates:
            best = min(candidates, key=lambda x: cx - x[0])
            used_keys.add(best[2])
            cards.append({"name": name_box.name, "key": best[2], "x": cx})
        else:
            cards.append({"name": name_box.name, "key": None, "x": cx})

    # 推断缺失的按键
    if hand_count is not None and len(cards) < hand_count:
        # 手牌数 > 识别到的卡牌数，按位置顺序依次分配
        sorted_cards = sorted(enumerate(cards), key=lambda x: x[1]["x"])
        next_key = 1
        for idx, c in sorted_cards:
            if c["key"] is not None:
                next_key = int(c["key"]) + 1
            else:
                c["key"] = str(next_key)
                next_key += 1
    elif hand_count is not None and hand_count == len(cards):
        # 手牌数与识别数一致，直接用顺序分配
        for i, c in enumerate(cards):
            expected = i + 1
            if c["key"] is None:
                c["key"] = str(expected)
    else:
        # 无法读取手牌数，用简单推断
        for i, c in enumerate(cards):
            if c["key"] is None:
                c["key"] = str(i + 1)

    task.log_info(f"_hand_cards: 识别到 {len(cards)} 张手牌: {[(c['name'], c['key']) for c in cards]}")
    return cards


def _try_all_card_keys(task: TriggerTask, count):
    """从当前手牌数向下尝试所有手牌按键，兜底处理按键漏识别或识别错误。"""
    task.log_info(f"_try_all_card_keys: 手牌数={count}，发送按键 {min(count, 9)} 到 1")
    for index in range(min(count, 9), 0, -1):
        task.send_key(str(index))
        task.sleep(0.5)
        task.send_key("enter")
        task.sleep(1)


def _read_hand_count(task: TriggerTask):
    """读取当前手牌数；OCR 误识别成三位数时只取后两位纠正。"""
    box = find_box_at_point(task, 0.509, 0.972)
    match = re.search(r"(\d+)/10", box.name) if box else None
    if not match:
        return None
    hand_count_text = match.group(1)
    if len(hand_count_text) >= 3:
        corrected = hand_count_text[-2:]
        task.log_info(f"手牌数 OCR 识别为{hand_count_text}，纠正为{corrected}")
        hand_count_text = corrected
    hand_count = int(hand_count_text)
    if hand_count > 10:
        corrected = hand_count % 100
        task.log_info(f"手牌数 OCR 识别超过10: {hand_count}，纠正为{corrected}")
        hand_count = corrected
    return min(hand_count, 10)


def _read_member_slots(task: TriggerTask):
    """读取会合主战员选择页面中三个候选槽位的文本框。"""
    slots = []
    for x, y in [(0.320, 0.731), (0.592, 0.728), (0.850, 0.722)]:
        box = find_box_at_point(task, x, y)
        slots.append({"name": box.name if box else "", "x": x, "y": y, "refresh_y": 0.800})
    return slots


def _battle_member_boxes(task: TriggerTask):
    """读取出战主战员列表里的可点击主战员名称文本。"""
    _excluded = {"主战员列表", "甄别主战员", "确认", "返回", "等级", "Q", "6", "支援",
                 "治愈", "守护", "核心", "60", "令", "√", "攻", "弘命", "炫心",
                 "详细信息", "配置", "同步", "全部", "``"}
    matched = []
    for box in task.all_texts:
        cx = (box.x + box.width / 2) / task.width
        cy = (box.y + box.height / 2) / task.height
        in_x = 0.100 <= cx <= 0.984
        in_y = 0.100 <= cy <= 0.892
        excluded = box.name in _excluded
        task.log_debug(f"_battle_member_boxes: name=「{box.name}」 cx={cx:.4f} cy={cy:.4f} "
                       f"in_x={in_x} in_y={in_y} excluded={excluded}")
        if in_x and in_y and not excluded:
            matched.append(box)
    return matched


def _confirm_battle_member_selection(task: TriggerTask):
    """出战主战员选择后，按确认按钮色相决定确认或返回。"""
    dominant_hue = calculate_dominant_hue(task, (0.901, 0.931, 0.911, 0.941))
    if dominant_hue != -1 and 7 <= dominant_hue <= 17:
        task.log_info(f"出战主战员确认按钮色相={dominant_hue}，点击确认")
        task.click(0.906, 0.936)
        task.sleep(2)
    else:
        task.log_info(f"出战主战员确认按钮色相={dominant_hue}，未激活，返回")
        task.click(0.044, 0.050)
    return True


def _select_battle_member(task: TriggerTask, max_scrolls=5):
    """按出战主战员优先级选择列表角色；找不到配置角色则随机选择。"""
    priority = _get_battle_member_priority(task)
    task.log_info(f"出战主战员优先级配置: {priority}")
    for scroll_index in range(max_scrolls + 1):
        boxes = _battle_member_boxes(task)
        recognized_names = [box.name for box in boxes]
        task.log_info(f"第{scroll_index + 1}次扫描, OCR识别到的主战员: {recognized_names}")
        for name in priority:
            member = next((box for box in boxes if name in box.name), None)
            if member:
                task.log_info(f"出战主战员优先级匹配成功: 「{name}」->「{member.name}」")
                task.click_box(member)
                task.sleep(0.5)
                return _confirm_battle_member_selection(task)
            else:
                task.log_info(f"出战主战员优先级匹配失败: 「{name}」未在当前列表中")
        if scroll_index < max_scrolls:
            task.log_info(f"第{scroll_index + 1}次未匹配到任何优先级角色, 向下滚动重试")
            task.scroll_relative(0.5, 0.7, -3)
            task.sleep(0.5)
            task.all_texts = task.ocr()
    boxes = _battle_member_boxes(task)
    if not boxes:
        task.log_info("出战主战员列表为空，无法选择")
        return False
    member = random.choice(boxes)
    task.log_info(f"未找到配置中的出战主战员，随机选择「{member.name}」")
    task.click_box(member)
    task.sleep(0.5)
    return _confirm_battle_member_selection(task)


# ------------------------- 出击模式独有页面处理函数 -------------------------

def handle_boss_selection(task: TriggerTask):
    """首领选择页面: 随机选择一个首领并确认。"""
    box = find_box_at_point(task, 0.484, 0.928)
    if not (box and re.search(r"请选择.*遇见的首领", box.name)):
        return False
    bosses = []
    for x, y in [(0.358, 0.706), (0.641, 0.706)]:
        name_box = find_box_at_point(task, x, y)
        if name_box:
            bosses.append({"name": name_box.name, "x": x, "y": y})
    if not bosses:
        return False
    boss = random.choice(bosses)
    task.log_info(f"首领选择: 随机选择「{boss['name']}」")
    task.click(boss["x"], boss["y"])
    task.sleep(1)
    # task.click(0.919, 0.930)
    return True


def handle_battle_page(task: TriggerTask):
    """战斗页面: 优先按"出牌优先级"配置出牌；找不到优先级中的牌时按当前手牌数从大到小兜底尝试。"""
    hand_count = _read_hand_count(task)
    if hand_count is None:
        return False
    if hand_count == 0:
        finishturn_box = task.box_of_screen(0.844, 0.782, 0.998, 0.990)
        if not task.find_feature(feature_name="finishturn", box=finishturn_box):
            task.log_info("手牌数为0且未检测到finishturn特征，return True等待下一帧")
            return True

    card_names = _hand_card_names(task)
    cards = _hand_cards(task)

    if (cards or card_names):
        # 兜底策略：优先检测连续三轮卡牌名集合无变化（说明优先级匹配的牌打不出去）
        current_names = {c["name"] for c in cards if c["key"] is not None}
        if not hasattr(task, '_card_stuck_round'):
            task._card_stuck_round = 0
            task._last_card_names = set()
        if task._last_card_names and task._last_card_names == current_names:
            task._card_stuck_round += 1
            task.log_info(f"卡牌名连续{task._card_stuck_round}轮未变化，当前手牌: {current_names}")
            if task._card_stuck_round >= 3:
                task.log_info(f"卡牌名连续3轮未变化，执行兜底出牌")
                task._card_stuck_round = 0
                task._last_card_names = set()
                _try_all_card_keys(task, hand_count)
                return True
        else:
            task._card_stuck_round = 0
            task._last_card_names = current_names

        # 检查"出牌优先级"配置
        play_priority = _get_config_value(task, "出牌优先级", [])
        if play_priority and cards:
            for pri_name in play_priority:
                matched = next((c for c in cards if pri_name and (pri_name in c["name"] or c["name"] in pri_name) and c["key"] is not None), None)
                if matched:
                    task.log_info(f"出牌优先级匹配: 卡牌「{matched['name']}」→ 按键 {matched['key']}")
                    task.send_key(matched['key'])
                    task.sleep(1)
                    task.send_key("enter")
                    task.sleep(2)
                    if "极光" in matched["name"]:
                        task.log_info(f"卡牌「{matched['name']}」包含极光，额外等待2秒")
                        task.sleep(2)
                    elif "万众英雄" in matched["name"]:
                        task.log_info(f"卡牌「{matched['name']}」包含万众英雄，额外等待2秒")
                        task.sleep(2)
                    return True

        # 未命中优先级，兜底从大到小出牌
        task.log_info(f"未命中出牌优先级，按当前手牌数{hand_count}从大到小兜底出牌")
        _try_all_card_keys(task, hand_count)
        return True
    else:
        finishturn_box = task.box_of_screen(0.844, 0.782, 0.998, 0.990)
        if task.find_feature(feature_name="finishturn", box=finishturn_box):
            task.log_info("检测到finishturn特征，按E结束回合")
            task.send_key("e")
            task.sleep(1)
        return True
    return True


def handle_get_card(task: TriggerTask):
    """获得卡牌页面: 按优先级选择卡牌。"""
    title = find_box_at_point(task, 0.502, 0.128)
    tip = find_box_at_point(task, 0.883, 0.131)
    if not (title and title.name == "获得卡牌" and tip and re.search(r"请选择.*要获得的卡牌", tip.name)):
        return False
    cards = []
    for x, y in [(0.194, 0.310), (0.471, 0.311), (0.750, 0.310)]:
        box = find_box_at_point(task, x, y)
        if box:
            cards.append({"name": box.name, "x": x, "y": y})
    if not cards:
        return False
    for name in _get_config_value(task, "获得卡牌优先级", []):
        chosen = next((card for card in cards if name in card["name"]), None)
        if chosen:
            task.log_info(f"获得卡牌: 优先选择「{chosen['name']}」")
            task.click(chosen["x"], chosen["y"])
            task.sleep(0.5)
            task.click(0.912, 0.931)
            return True
    if _get_config_value(task, '跳过非优先级卡牌', True):
        task.log_info("获得卡牌: 未命中优先级，跳过非优先级卡牌")
        task.click(0.749, 0.931)
        task.sleep(1)
        return True
    chosen = random.choice(cards)
    task.log_info(f"获得卡牌: 随机选择「{chosen['name']}」")
    task.click(chosen["x"], chosen["y"])
    task.sleep(1)
    # task.click(0.912, 0.931)
    return True


def handle_draw_card_event(task: TriggerTask):
    """抽牌事件页面: 按获得卡牌优先级选择一张要手持的卡牌。"""
    title = find_box_at_point(task, 0.509, 0.108)
    if not (title and re.search(r"请选择.*手持的卡牌", title.name)):
        return False
    x1, y1, x2, y2 = 0.028, 0.211, 0.938, 0.857
    cards = [
        box for box in task.all_texts
        if x1 <= (box.x + box.width / 2) / task.width <= x2
        and y1 <= (box.y + box.height / 2) / task.height <= y2
        and box.name.strip()
    ]
    if not cards:
        return False
    chosen = None
    for name in _get_config_value(task, "获得卡牌优先级", []):
        chosen = next((card for card in cards if name in card.name), None)
        if chosen:
            task.log_info(f"抽牌事件: 优先选择「{chosen.name}」")
            break
    if chosen is None:
        chosen = random.choice(cards)
        task.log_info(f"抽牌事件: 未命中优先级，随机选择「{chosen.name}」")
    task.click_box(chosen)
    task.sleep(1)
    # task.click(0.952, 0.933)
    return True


def handle_discard_hand_card(task: TriggerTask):
    """手牌中仍有可用卡牌提示: 点击丢弃手牌。"""
    box = find_box_at_point(task, 0.5, 0.356)
    if box and "手牌中仍有可用卡牌" in box.name:
        task.log_info("检测到手牌丢弃页面，点击丢弃")
        task.click(0.424, 0.500) #今日不再提示
        task.sleep(0.5)
        task.click(0.663, 0.607)
        return True
    return False


def handle_sortie_reward_settlement(task: TriggerTask):
    """出击模式奖励结算页面: 按配置领取奖励或关闭页面。"""
    title = find_box_at_point(task, 0.550, 0.068)
    if not (title and title.name == "结算"):
        return False
    reward_box = find_box_at_point(task, 0.848, 0.389)
    if reward_box and reward_box.name == "获得" and _get_config_value(task, "领取奖励", False):
        task.log_info("检测到出击模式奖励结算页面，领取奖励")
        task.click_box(reward_box)
        task.sleep(1)
        return True
    task.log_info("检测到出击模式奖励结算页面，关闭页面")
    task.click(0.959, 0.057)
    task.sleep(1)
    return True


def handle_sortie_reward_claim(task: TriggerTask):
    """出击模式奖励领取页面: 按配置领取或放弃卡厄思战利品。"""
    title = find_box_at_point(task, 0.503, 0.335)
    if not (title and re.search(r"卡.*思战利品", title.name)):
        return False
    if _get_config_value(task, "领取奖励", False):
        task.log_info("检测到出击模式奖励领取页面，领取卡厄思战利品")
        task.click(0.567, 0.708)
        task.sleep(1)
        return True
    task.log_info("检测到出击模式奖励领取页面，放弃卡厄思战利品")
    task.click(0.355, 0.714)
    return True


def handle_battle_member_config(task: TriggerTask):
    """主战员配置页面: 区分出战主战员入口和确认进入入口。"""
    title = find_box_at_point(task, 0.130, 0.043)
    if not (title and title.name == "主战员配置"):
        return False
    battle_member_hint = find_box_at_point(task, 0.188, 0.799)
    if not (battle_member_hint and battle_member_hint.name.strip()):
        task.log_info("检测到主战员配置页面: 当前处于出战主战员，点击出战主战员入口")
        task.click(0.315, 0.475)
        task.sleep(2)
        return True
    task.log_info("检测到主战员配置页面: 点击进入")
    task.click(0.719, 0.914)
    return True


def handle_battle_member_selection(task: TriggerTask):
    """出战主战员列表页面: 按配置优先级选择角色。"""
    title = find_box_at_point(task, 0.139, 0.044)
    right_hint = find_box_at_point(task, 0.562, 0.044)
    if not ((title and  "主战员列表" in title.name) and  (right_hint and "甄别主战员" in right_hint.name)):
        return False
    return _select_battle_member(task)


def handle_member_selection(task: TriggerTask):
    """主战员选择页面: 优先选配置角色（跳过拉黑角色）；没有则点击每个名字下方按钮刷新一次，仍没有就随机选（跳过拉黑角色）。"""
    prompt = find_box_at_point(task, 0.500, 0.931)
    if not (prompt and "主战员" in prompt.name):
        return False
    priority = _get_member_priority(task)
    blacklisted = _get_blacklisted_members(task)
    task.log_info(f"主战员选择: 优先级={priority}, 拉黑列表={blacklisted}")

    def not_blacklisted(slot):
        return not any(blk in slot["name"] for blk in blacklisted)

    slots = _read_member_slots(task)
    chosen = None
    for name in priority:
        chosen = next((slot for slot in slots if name in slot["name"] and not_blacklisted(slot)), None)
        if chosen:
            task.log_info(f"主战员选择: 优先选择「{chosen['name']}」")
            break
    if chosen is None:
        task.log_info("主战员选择: 未找到优先角色或优先角色被拉黑，点击三个名字下方按钮刷新一次")
        for slot in slots:
            task.click(slot["x"], slot["refresh_y"])
            task.sleep(0.5)
        task.sleep(1)
        task.all_texts = task.ocr()
        slots = _read_member_slots(task)
        for name in priority:
            chosen = next((slot for slot in slots if name in slot["name"] and not_blacklisted(slot)), None)
            if chosen:
                task.log_info(f"主战员选择: 刷新后选择「{chosen['name']}」")
                break
    if chosen is None:
        valid_slots = [slot for slot in slots if slot["name"] and not_blacklisted(slot)]
        if not valid_slots:
            valid_slots = [slot for slot in slots if slot["name"]]
            if not valid_slots:
                return False
            task.log_info("主战员选择: 所有候选都被拉黑，从全部候选中随机选择")
        chosen = random.choice(valid_slots)
        task.log_info(f"主战员选择: 未找到优先角色，随机选择「{chosen['name']}」")
    task.click(chosen["x"], chosen["y"])
    task.sleep(0.5)
    task.click(0.884, 0.931)
    task.sleep(0.5)
    task.click(0.635, 0.639)
    task.sleep(0.5)
    return True


def handle_ether_supply(task: TriggerTask):
    """以太补充页面: 根据配置决定是否使用体力。"""
    box = find_box_at_point(task, 0.502, 0.139)
    if box and box.name == "以太补充":
        task.log_info("检测到以太补充页面")
        if _get_config_value(task, '使用体力药', False):
            task.click(0.669, 0.808)
            task.sleep(1)
        else:
            task.click(0.347, 0.803)
        return True
    return False


def handle_battle_hand_select(task: TriggerTask):
    """战斗中手牌选择页面: 检测到请选择卡牌文本且底部有手牌数，随机选择指定数量的卡牌。"""
    # 检测(0.5, 0.111)位置的提示文本
    prompt = find_box_at_point(task, 0.5, 0.111)
    if not prompt:
        return False
    m = re.search(r'请选择(?=.*卡牌).*?(\d+)张', prompt.name)
    if not m:
        return False

    # 检测(0.505, 0.971)是否有手牌数 x/10
    hand_box = find_box_at_point(task, 0.505, 0.971)
    if not (hand_box and re.search(r'\d+/10', hand_box.name)):
        return False

    need = int(m.group(1))
    task.log_info(f"检测到战斗中手牌选择页面，需选择{need}张卡牌，随机选择")

    selected = 0
    for _ in range(need):
        task.all_texts = _simplify_texts(task.ocr())
        cards = [
            b for b in task.all_texts
            if 0.116 <= (b.x + b.width / 2) / task.width <= 0.859
            and 0.697 <= (b.y + b.height / 2) / task.height <= 0.908
            and len(b.name.strip()) > 1
            and b.name not in ["确认", "返回", "跳过"]
        ]
        if not cards:
            task.log_info("手牌区域未找到卡牌，停止选择")
            break
        chosen = random.choice(cards)
        task.log_info(f"选择手牌: {chosen.name}")
        task.click_box(chosen)
        selected += 1
        task.sleep(1)

    if selected > 0:
        task.log_info(f"已完成选择，点击确认")
        task.click(0.934, 0.883)
        task.sleep(1)
    return True


def handle_curiosity_activate(task: TriggerTask):
    """尼娅的好奇心发动页面: 按优先级选择要手持的卡牌（战斗相关页面，优先级高于战斗页面）。"""
    box = find_box_at_point(task, 0.499, 0.129)
    if box and "请选择要手持的卡牌" in box.name:
        task.log_info("检测到尼娅的好奇心发动页面")
        priority = ["剑雨", "展开极光", "一缕光芒", "万众英雄"]
        px1, py1 = int(0.168 * task.width), int(0.247 * task.height)
        px2, py2 = int(0.868 * task.width), int(0.318 * task.height)
        cards = [
            b for b in task.all_texts
            if b.x >= px1 and b.y >= py1 and b.x + b.width <= px2 and b.y + b.height <= py2
            and b.name not in ["确认", "返回", "跳过"]
        ]
        chosen_card = None
        for pri_name in priority:
            for card in cards:
                if card.name in pri_name:
                    chosen_card = card
                    task.log_info(f"按优先级选择卡牌: {card.name}")
                    break
            if chosen_card:
                break
        if not chosen_card and cards:
            chosen_card = random.choice(cards)
            task.log_info(f"未命中优先级，随机选择卡牌: {chosen_card.name}")
        if chosen_card:
            task.click_box(chosen_card)
            task.sleep(2)
            return True
    return False


def handle_extra_card_use(task: TriggerTask):
    """额外使用卡牌页面: 随机选择一张卡牌使用（战斗相关页面，优先级高于战斗页面）。"""
    box = find_box_at_point(task, 0.498, 0.131)
    if box and "请选择张要额外使用的卡牌" in box.name:
        task.log_info("检测到额外使用卡牌页面，随机选择")
        task.click(*random.choice([(0.251, 0.546), (0.508, 0.518), (0.764, 0.525)]))
        task.sleep(2)
        return True
    return False


def handle_card_function_select(task: TriggerTask):
    """卡牌功能选择页面: 量子晶种预测选创造，小丑任务随机选任务（战斗相关页面，优先级高于战斗页面）。"""
    title = find_box_at_point(task, 0.499, 0.131)
    if not (title and "请选择功能" in title.name):
        return False
    task_positions = [(0.115, 0.286), (0.349, 0.289), (0.588, 0.290), (0.827, 0.287)]
    task_boxes = [find_box_at_point(task, x, y) for x, y in task_positions]
    if all(b and "任务" in b.name for b in task_boxes):
        chosen = random.choice(task_boxes)
        task.log_info(f"检测到小丑任务选择卡牌发动，随机选择一项任务")
        task.click_box(chosen)
        task.sleep(4)
        return True
    p1 = find_box_at_point(task, 0.214, 0.289)
    p2 = find_box_at_point(task, 0.470, 0.292)
    p3 = find_box_at_point(task, 0.722, 0.286)
    if p1 and p2 and p3 and "创造" in p1.name and "创造" in p2.name and "创造" in p3.name:
        task.log_info("检测到量子晶种预测卡牌页面，点击创造")
        task.click(0.722, 0.286)
        task.sleep(4)
        return True
    cards = [
        b for b in task.all_texts
        if 0.023 <= (b.x + b.width / 2) / task.width <= 0.970
        and 0.239 <= (b.y + b.height / 2) / task.height <= 0.312
        and len(b.name.strip()) > 1
        and b.name not in ["确认", "返回", "跳过"]
    ]
    if cards:
        chosen = random.choice(cards)
        task.log_info(f"卡牌功能选择兜底: 随机点击卡牌「{chosen.name}」")
        task.click_box(chosen)
        task.sleep(4)
        return True
    return False


def handle_return_to_draw_pile(task: TriggerTask):
    """选择手牌放回抽牌堆页面: 从左往右选择第一张（战斗相关页面，优先级高于战斗页面）。"""
    box = find_box_at_point(task, 0.484, 0.111)
    if not (box and re.search(r"请选择.*要移动至抽牌堆.*", box.name)):
        return False
    task.log_info("检测到选择手牌放回抽牌堆页面，从左往右选择第一张")
    cards = sorted(
        [b for b in task.all_texts
         if 0.116 <= (b.x + b.width / 2) / task.width <= 0.859
         and 0.697 <= (b.y + b.height / 2) / task.height <= 0.908
         and len(b.name.strip()) > 1
         and b.name not in ["确认", "返回", "跳过"]],
        key=lambda b: b.x
    )
    if not cards:
        task.log_info("未找到手牌")
        return False
    chosen = cards[0]
    task.click_box(chosen)
    task.sleep(1)
    # task.click(0.934, 0.883)
    # task.sleep(1)
    return True


def handle_escape(task: TriggerTask):
    """逃脱页面: 检测战利品与逃脱按钮后点击逃脱。"""
    title = find_box_at_point(task, 0.675, 0.164)
    escape_box = find_box_at_point(task, 0.952, 0.928)
    if title and title.name == "战利品" and escape_box and escape_box.name == "逃脱":
        task.log_info("检测到逃脱页面，点击逃脱")
        task.click_box(escape_box)
        task.sleep(0.5)
        return True
    return False



# 出击模式 PAGE_HANDLERS
PAGE_HANDLERS = [
    log_credit,

    handle_close_button, #关闭按钮
    handle_card_assign,
    handle_confirm, #确认按钮
    handle_remove, #移除按钮
    handle_flash, #闪光按钮
    handle_reflash, #重新闪光按钮
    handle_grant_flash, #赋予闪光按钮
    handle_copy, #复制按钮
    handle_leave, #离开按钮
    handle_select, #选择按钮

    handle_equipment_recast, #装备重铸按钮
    handle_rest,

    handle_non_battle_page,
    handle_battle_crash,
    handle_discard_hand_card,
    handle_battle_hand_select,
    handle_curiosity_activate,
    handle_extra_card_use,
    handle_card_function_select,
    handle_return_to_draw_pile,
    handle_weakness_info,
    handle_battle_page,
    handle_close_page,
    handle_ether_supply,
    # handle_center_confirm,
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_boss_selection,
    handle_card_reward,
    handle_get_card,
    handle_draw_card_event,
    handle_equipment,
    # handle_mask_card,
    handle_remove_card,
    handle_copy_member,
    handle_copy_card,
    handle_flash_card,
    handle_copy_card_pick,
    handle_convert_card,
    handle_negotiation,
    handle_sortie_reward_settlement,
    handle_sortie_reward_claim,
    handle_continue,
    handle_battle_member_selection,
    handle_member_selection,
    handle_battle_member_config,
    handle_enter,
    handle_route_selection,
    handle_obtain_reward,
    handle_view_original,
    handle_battle_failed,
    handle_data_collected,
    handle_mental_breakdown,
    handle_trauma_center,
    handle_treating,
    handle_treat_approve,
    handle_explore_result,
    handle_expedition_unlock,
    handle_cares_tip,
    handle_skip,
    handle_event_task,
    handle_escape,
    handle_weakness_info,
    handle_minimizemap,
    handle_held_cards_page,
    handle_unknown_page,
]
