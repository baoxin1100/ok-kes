from ok import TriggerTask

from utils import (
    _simplify_texts, _edit_distance, _get_config_value, _get_card_list, _get_route_priority, _get_game_text,
    find_box_at_point, find_text, find_exact_text,
    _card_has_type_below, select_card, identify_node_type, calculate_dominant_hue,
    log_credit, log_node_status, handle_battle_crash, handle_close_page,
    handle_center_confirm, handle_settlement, handle_skip,
    handle_destiny_choice, handle_main_member_flash,
    handle_card_reward, handle_equipment,
    handle_select_card, handle_copy_member,
    handle_convert_card,
    handle_negotiation, handle_continue, handle_confirm, handle_enter,
    handle_event_task, handle_route_selection, handle_obtain_reward,
    handle_leave, handle_next_step, handle_select, handle_view_original,
    handle_close_button,
    handle_card_assign, handle_non_battle_page,
    handle_remove, handle_flash, handle_reflash, handle_grant_flash, handle_copy, handle_convert, handle_equipment_recast, handle_weakness_info, handle_minimizemap,
    handle_held_cards_page, handle_unknown_page,
    is_frame_stuck, handle_stuck_log, is_button_active, _clean_match,
    handle_shop, handle_expedition_result,
    handle_escape,
    _get_current_credit
)

import re
import random
import cv2


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


def _is_card_name(name):
    """判断文本是否为卡牌名：排除类型标签。"""
    exclude_keywords = {"攻击", "强化", "技能", "咒术", "基础", "基本", "状态异常", "诅咒"}
    # 包含类型关键词的文本不是卡牌名
    if any(kw in name for kw in exclude_keywords):
        return False
    # 包含"攻"且长度<=3的文本不是卡牌名（如"X攻"、"基本攻"）
    if "攻" in name and len(name) <= 3:
        return False
    return True


def _hand_card_names(task: TriggerTask):
    """读取手牌区域内的卡牌名，排除按键和类型标签文本。"""
    x1, y1, x2, y2 = 0.159, 0.683, 0.836, 0.831

    # 打印所有文本及其坐标，帮助判断手牌区域过滤问题
    task.log_info(f"_hand_card_names 区域: cx=[{x1}, {x2}], cy=[{y1}, {y2}]")
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        in_region = x1 <= cx <= x2 and y1 <= cy <= y2
        has_key = _card_key(b.name)
        name_len = len(b.name.strip())
        task.log_info(f"  OCR: 「{b.name}」 cx={cx:.4f} cy={cy:.4f} in_region={in_region} has_key={has_key} len={name_len}")

    boxes = [b for b in task.all_texts
             if x1 <= (b.x + b.width / 2) / task.width <= x2
             and y1 <= (b.y + b.height / 2) / task.height <= y2]
    result = [b for b in boxes
              if not _card_key(b.name)
              and len(b.name.strip()) > 1
              and _is_card_name(b.name)]
    task.log_info(f"_hand_card_names 区域共{len(boxes)}个文本，过滤后剩{len(result)}个: {[b.name for b in result]}")
    return result


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
        left_x = (name_box.x) / task.width  # 使用左边缘坐标，避免文本长度影响间距判断
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
            cards.append({"name": name_box.name, "key": best[2], "x": cx, "left_x": left_x})
        else:
            cards.append({"name": name_box.name, "key": None, "x": cx, "left_x": left_x})

    # 推断缺失的按键：用最小相邻间距作为 expected_spacing 进行插值
    # 以最近的前一张已有按键的卡牌为基准推算，避免累积误差
    if len(cards) >= 2:
        sorted_cards = sorted(enumerate(cards), key=lambda x: x[1]["left_x"])
        # 计算相邻卡牌 left_x 的最小间距
        min_spacing = float('inf')
        for i in range(len(sorted_cards) - 1):
            spacing = sorted_cards[i + 1][1]["left_x"] - sorted_cards[i][1]["left_x"]
            if spacing < min_spacing:
                min_spacing = spacing
        expected_spacing = max(0.055, min_spacing)  # 从0.055和最小间距中取最大值，防止除零
        task.log_info(f"_hand_cards: 最小间距={min_spacing:.4f}")
        # 确保最左边的卡牌有按键，如果没有则分配1
        if sorted_cards[0][1]["key"] is None:
            sorted_cards[0][1]["key"] = "1"
            task.log_info(f"_hand_cards: 卡牌「{sorted_cards[0][1]['name']}」 left_x={sorted_cards[0][1]['left_x']:.4f} → 最左卡牌分配按键1")
        for i in range(1, len(sorted_cards)):
            idx, c = sorted_cards[i]
            if c["key"] is None:
                # 向前查找最近一张已有按键的卡牌
                for j in range(i - 1, -1, -1):
                    prev_idx, prev_c = sorted_cards[j]
                    if prev_c["key"] is not None:
                        offset = (c["left_x"] - prev_c["left_x"]) / expected_spacing
                        approx_key = int(prev_c["key"]) + round(offset)
                        if 1 <= approx_key <= 9:
                            c["key"] = str(approx_key)
                            task.log_info(f"_hand_cards: 卡牌「{c['name']}」 left_x={c['left_x']:.4f} 基于「{prev_c['name']}」(key={prev_c['key']}) offset={offset:.2f} → {c['key']}")
                        else:
                            task.log_info(f"_hand_cards: 卡牌「{c['name']}」 left_x={c['left_x']:.4f} 基于「{prev_c['name']}」(key={prev_c['key']}) offset={offset:.2f} → 推算={approx_key}超出1-9，不分配")
                        break
    elif len(cards) == 1:
        if cards[0]["key"] is None:
            cards[0]["key"] = "1"
            task.log_info(f"_hand_cards: 单张卡牌，分配按键1")

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
        name = box.name if box else ""
        if box:
            task.log_info(f"_read_member_slots: 槽位({x},{y}) 识别到名称=「{name}」 box_x={box.x} box_y={box.y} box_w={box.width} box_h={box.height}")
        else:
            task.log_info(f"_read_member_slots: 槽位({x},{y}) 未识别到任何文本")
        slots.append({"name": name, "x": x, "y": y, "refresh_y": 0.800})
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


# 主战员名称 → 模板特征名映射字典（用于OCR识别不到时的模板匹配兜底）
_MEMBER_FEATURE_MAP = {
    "九": "nine",
}


def _select_battle_member(task: TriggerTask, max_scrolls=5):
    """按出战主战员优先级选择列表角色；找不到配置角色则随机选择。"""
    priority = _get_battle_member_priority(task)
    task.log_info(f"出战主战员优先级配置: {priority}")
    for scroll_index in range(max_scrolls + 1):
        boxes = _battle_member_boxes(task)
        recognized_names = [box.name for box in boxes]
        task.log_info(f"第{scroll_index + 1}次扫描, OCR识别到{len(boxes)}个主战员:")
        for b in boxes:
            cx = (b.x + b.width / 2) / task.width
            cy = (b.y + b.height / 2) / task.height
            task.log_info(f"  box: name=「{b.name}」 cx={cx:.4f} cy={cy:.4f} x={b.x} y={b.y} w={b.width} h={b.height}")
        for name in priority:
            member = next((box for box in boxes if name in box.name), None)
            if member:
                cx = (member.x + member.width / 2) / task.width
                cy = (member.y + member.height / 2) / task.height
                task.log_info(f"出战主战员优先级匹配成功: 配置名「{name}」-> OCR名「{member.name}」 cx={cx:.4f} cy={cy:.4f} x={member.x} y={member.y} w={member.width} h={member.height}")
                task.click_box(member)
                task.sleep(0.5)
                return _confirm_battle_member_selection(task)
            else:
                # OCR 未匹配到，尝试用模板匹配兜底
                feature_name = _MEMBER_FEATURE_MAP.get(name)
                if feature_name and task.feature_exists(feature_name):
                    task.log_info(f"出战主战员OCR未匹配到「{name}」，尝试模板匹配 feature=「{feature_name}」")
                    search_box = task.box_of_screen(0.096, 0.097, 0.988, 0.896)
                    feature_box = task.find_one(feature_name=feature_name, box=search_box, threshold=0.5)
                    if feature_box:
                        cx = (feature_box.x + feature_box.width / 2) / task.width
                        cy = (feature_box.y + feature_box.height / 2) / task.height
                        task.log_info(f"出战主战员模板匹配成功: 配置名「{name}」 feature=「{feature_name}」 cx={cx:.4f} cy={cy:.4f}, 相似度={feature_box.confidence:.4f}")
                        task.click_box(feature_box)
                        task.sleep(0.5)
                        return _confirm_battle_member_selection(task)
                    else:
                        task.log_info(f"出战主战员模板匹配失败: 「{name}」(feature=「{feature_name}」) 未找到")
                else:
                    task.log_info(f"出战主战员优先级匹配失败: 「{name}」未在当前列出的{len(boxes)}个主战员中")
        if scroll_index < max_scrolls:
            task.log_info(f"第{scroll_index + 1}次未匹配到任何优先级角色, 向下滚动重试")
            task.scroll_relative(0.5, 0.7, -3)
            task.sleep(0.5)
            task.all_texts = _simplify_texts(task.ocr())
    boxes = _battle_member_boxes(task)
    if not boxes:
        task.log_info("出战主战员列表为空，无法选择")
        return False
    member = random.choice(boxes)
    cx = (member.x + member.width / 2) / task.width
    cy = (member.y + member.height / 2) / task.height
    task.log_info(f"未找到配置中的出战主战员，随机选择「{member.name}」 cx={cx:.4f} cy={cy:.4f} x={member.x} y={member.y} w={member.width} h={member.height}")
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

    # 如果已到达最终boss节点，标记boss战状态
    if hasattr(task, 'node_status') and task.node_status.get('reach_final_boss', False):
        task.node_status['final_boss_battle'] = True
        task.log_info("检测到最终boss战斗开始，final_boss_battle=True")

    # 检测战斗画面是否卡住
    if is_frame_stuck(task):
        task.log_info("战斗画面卡住，从手牌区拖拽一张卡牌尝试恢复")
        hand_x = random.uniform(0.200, 0.800)
        hand_y = random.uniform(0.700, 0.830)
        task.swipe_relative(hand_x, hand_y, 0.5, 0.3, duration=0.3)
        task.sleep(1)
        return True

    # 检测 EP 能量条是否满（0.032,0.947 处 RGB 接近 (193,255,255)）
    ep_px = int(0.032 * task.width)
    ep_py = int(0.947 * task.height)
    if 0 <= ep_px < task.width and 0 <= ep_py < task.height:
        ep_region = task.frame[max(0, ep_py-2):ep_py+3, max(0, ep_px-2):ep_px+3, :3]
        if ep_region.size > 0:
            avg_bgr = cv2.mean(ep_region)[:3]
            # OpenCV 是 BGR 格式，用户描述的是 RGB(193,255,255) → BGR(255,255,193)
            avg_b, avg_g, avg_r = avg_bgr
            task.log_info(f"EP能量条区域颜色: B={avg_b:.1f} G={avg_g:.1f} R={avg_r:.1f} (期望接近 B=255 G=255 R=193)")
            if abs(avg_b - 255) <= 15 and abs(avg_g - 255) <= 15 and abs(avg_r - 193) <= 15:
                task.log_info("EP能量达到最大值，随机释放Ego技能")
                task.send_key(random.choice(["F1", "F2", "F3"]))
                task.sleep(1)
                task.send_key("enter")
                task.sleep(4)
                return True

    finishturn_box = task.box_of_screen(0.844, 0.782, 0.998, 0.990)
    if not task.find_feature(feature_name="finishturn", box=finishturn_box):
        task.log_info("未检测到finishturn特征，return True等待下一帧")
        return True

    card_names = _hand_card_names(task)
    cards = _hand_cards(task)

    if (cards or card_names):
        # 出牌卡手检测：追踪上一次尝试打出的卡牌是否连续多轮仍留在手牌中
        if not hasattr(task, '_play_stuck_count'):
            task._play_stuck_count = 0
        if not hasattr(task, '_last_attempted_card'):
            task._last_attempted_card = None

        # 检查"出牌优先级"配置
        play_priority = _get_config_value(task, "出牌优先级", [])
        if play_priority and cards:
            for pri_name in play_priority:
                matched = next((c for c in cards if pri_name and (pri_name in c["name"] or c["name"] in pri_name) and c["key"] is not None), None)
                if matched:
                    # 检测当前匹配到的卡牌是否与上次尝试打出的是同一张且仍在手牌中
                    if task._last_attempted_card == matched["name"]:
                        task._play_stuck_count += 1
                        task.log_info(f"卡牌「{matched['name']}」连续{task._play_stuck_count + 1}次尝试未出掉")
                        if task._play_stuck_count >= 3:
                            task.log_info(f"卡牌「{matched['name']}」连续3次未出掉，执行兜底出牌")
                            task._last_attempted_card = None
                            task._play_stuck_count = 0
                            _try_all_card_keys(task, hand_count)
                            return True
                    else:
                        task._last_attempted_card = matched["name"]
                        task._play_stuck_count = 0

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

        # 未命中出牌优先级，重置卡手状态
        task._last_attempted_card = None
        task._play_stuck_count = 0
        # 兜底从大到小出牌
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
    if not (title and title.name == "获得卡牌" and tip and re.search(r"请选择.*获得的卡牌", tip.name)):
        return False
    cards = []
    for x, y in [(0.194, 0.310), (0.471, 0.311), (0.750, 0.310)]:
        box = find_box_at_point(task, x, y)
        if box:
            box_info = f"name=「{box.name}」 x={box.x} y={box.y} w={box.width} h={box.height}"
            task.log_info(f"获得卡牌: 槽位({x},{y}) 识别到 {box_info}")
            cards.append({"name": box.name, "x": x, "y": y})
        else:
            task.log_info(f"获得卡牌: 槽位({x},{y}) 未识别到任何文本")
    if not cards:
        task.log_info("获得卡牌: 三个槽位均未识别到卡牌，无法选择")
        return False

    priority = _get_config_value(task, "获得卡牌优先级", [])
    task.log_info(f"获得卡牌: 识别到{len(cards)}张卡牌: {[c['name'] for c in cards]}, 当前优先级配置: {priority}")
    for name in priority:
        task.log_info(f"获得卡牌: 检查优先级「{name}」是否在卡牌列表中")
        chosen = next((card for card in cards if name in card["name"]), None)
        if chosen:
            task.log_info(f"获得卡牌: 优先选择「{chosen['name']}」(匹配优先级「{name}」)")
            task.click(chosen["x"], chosen["y"])
            task.sleep(0.5)
            task.click(0.912, 0.931)
            return True
    if _get_config_value(task, '跳过非优先级卡牌', True):
        task.log_info("获得卡牌: 未命中任何优先级卡牌，跳过非优先级卡牌")
        task.click(0.749, 0.931)
        task.sleep(1)
        return True
    chosen = random.choice(cards)
    task.log_info(f"获得卡牌: 跳过非优先级卡牌配置为False，随机选择「{chosen['name']}」")
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
    # task.click(0.959, 0.057)
    # task.sleep(1)
    return False


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
    if not (title and _get_game_text(task, '主战员配置') in title.name):
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
    if not ((title and  _get_game_text(task, '主战员列表') in title.name) and  (right_hint and _get_game_text(task, '甄别主战员') in right_hint.name)):
        return False
    return _select_battle_member(task)


def handle_member_selection(task: TriggerTask):
    """主战员选择页面: 优先选配置角色（跳过拉黑角色）；没有则点击每个名字下方按钮刷新一次，仍没有就随机选（跳过拉黑角色）。"""
    prompt = find_box_at_point(task, 0.500, 0.931)
    if not (prompt and _get_game_text(task, '主战员') in prompt.name):
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
            task.sleep(1)
        task.sleep(1)
        task.all_texts = _simplify_texts(task.ocr())
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
    task.sleep(1)
    # task.click(0.884, 0.931)
    # task.sleep(0.5)
    # task.click(0.635, 0.639)
    # task.sleep(0.5)
    return True


def handle_rational_supply(task: TriggerTask):
    """补充理性页面: 确认按钮未激活时关闭领取奖励并放弃补充。"""
    # 在区域(0.438,0.101,0.561,0.250)内查找包含"补充理性"的文本
    x1, y1, x2, y2 = 0.438, 0.101, 0.561, 0.250
    title = next((b for b in task.all_texts
                  if x1 <= (b.x + b.width / 2) / task.width <= x2
                  and y1 <= (b.y + b.height / 2) / task.height <= y2
                  and "补充理性" in b.name), None)
    if not title:
        return False
    task.log_info("检测到补充理性页面")
    confirm_box = find_box_at_point(task, 0.664, 0.774)
    if confirm_box and _clean_match(confirm_box.name, "确认") and not is_button_active(task, confirm_box):
        task.log_info("确认按钮未激活，将领取奖励设置为False，点击放弃补充")
        task.config['领取奖励'] = False
        from ok.gui.Communicate import communicate
        communicate.task_list_updated.emit()
        task.click(0.352, 0.774)
        task.sleep(1)
        return True
    return False


def handle_ether_supply(task: TriggerTask):
    """以太补充页面: 提示用户手动补充以太。"""
    box = find_box_at_point(task, 0.502, 0.139)
    if box and box.name == _get_game_text(task, '以太补充'):
        task.log_info("检测到以太补充页面，请手动补充以太后再启动功能")
        task.click(0.347, 0.803)
        task.sleep(0.5)
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

    _card_exclude_keywords = {"攻击", "强化", "技能", "咒术", "基础", "基本", "状态异常", "诅咒"}
    selected = 0
    for _ in range(need):
        task.all_texts = _simplify_texts(task.ocr())
        cards = [
            b for b in task.all_texts
            if 0.116 <= (b.x + b.width / 2) / task.width <= 0.859
            and 0.697 <= (b.y + b.height / 2) / task.height <= 0.878
            and len(b.name.strip()) > 1
            and b.name not in ["确认", "返回", "跳过"]
            and not any(kw in b.name for kw in _card_exclude_keywords)
            and not ("攻" in b.name and len(b.name) <= 3)
        ]
        if not cards:
            task.log_info("手牌区域未找到卡牌，随机在手牌区域内点击一个位置")
            rx = random.uniform(0.216, 0.759)
            ry = random.uniform(0.697, 0.878)
            task.click(rx, ry)
            selected += 1
            task.sleep(1)
            continue
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
    if box and _get_game_text(task, '请选择要手持的卡牌') in box.name:
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





def handle_rest_sortie(task: TriggerTask):
    """出击模式休息页面: 包含休息和闪光两个功能，检测到对应条件分别处理。"""
    # 检测闪光区域 (0.788,0.463)-(0.870,0.594) 是否存在"闪光"和"30"
    flash_x1, flash_y1, flash_x2, flash_y2 = 0.788, 0.463, 0.870, 0.594
    has_flash_text = False
    has_flash_cost = False
    flash_box = None
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if flash_x1 <= cx <= flash_x2 and flash_y1 <= cy <= flash_y2:
            if "闪光" in b.name:
                has_flash_text = True
                flash_box = b
            if "30" in b.name:
                has_flash_cost = True

    if has_flash_text and has_flash_cost and flash_box and hasattr(task, 'node_status') and task.node_status.get('flash_or_rest', False):
        task.log_info("休息区存在可闪光选项")

        # 获取当前信用点
        credit = _get_current_credit(task)
        task.log_info(f"当前信用点: {credit}")

        # 获取当前生命值百分比
        hp_percent = 100
        hp_box = find_box_at_point(task, 0.209, 0.040)
        if hp_box:
            hp_match = re.search(r'(\d+)/(\d+)', hp_box.name)
            if hp_match:
                current_hp = int(hp_match.group(1))
                max_hp = int(hp_match.group(2))
                if max_hp > 0:
                    hp_percent = int(current_hp * 100 / max_hp)
                    task.log_info(f"当前生命值: {current_hp}/{max_hp} = {hp_percent}%")

        flash_threshold_str = _get_config_value(task, '生命值大于多少优先闪光(百分比)', "60")
        try:
            flash_threshold = int(flash_threshold_str)
        except (ValueError, TypeError):
            flash_threshold = 60
        task.log_info(f"生命值={hp_percent}%, 阈值={flash_threshold}%, 信用点={credit}")
        if credit > 30 and hp_percent >= flash_threshold:
            task.log_info("满足闪光条件，点击闪光")
            task.click_box(flash_box)
            task.sleep(2)
            task.node_status['flash_or_rest'] = False
            return True
        else:
            task.log_info("不满足闪光条件，继续检测休息")

    # 检测休息区域 (0.298,0.681)-(0.420,0.850) 是否存在"休息"+"免费"
    x1, y1, x2, y2 = 0.298, 0.681, 0.420, 0.850
    has_rest = False
    has_free = False
    rest_box = None
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            if b.name == "休息":
                has_rest = True
                rest_box = b
            if "免费" in b.name:
                has_free = True
    if has_rest and has_free and rest_box and hasattr(task, 'node_status') and task.node_status.get('flash_or_rest', False):
        task.log_info("检测到休息界面，点击休息")
        task.click_box(rest_box)
        task.sleep(1)
        task.node_status['flash_or_rest'] = False
        return True

    # 检测是否需要进入德朗商店
    shop_box = find_box_at_point(task, 0.360, 0.138)
    if shop_box and "德朗商店" in shop_box.name and hasattr(task, 'node_status') and task.node_status.get('shop', False):
        task.log_info("检测到德朗商店，且 node_status['shop']=True，进入商店")
        task.click_box(shop_box)
        task.sleep(2)
        task.node_status['shop'] = False
        return True
    return False


# 出击模式 PAGE_HANDLERS
PAGE_HANDLERS = [
    log_credit,
    log_node_status,
    handle_stuck_log,

    handle_ether_supply,
    handle_center_confirm,
    handle_equipment, #装备选择
    handle_card_assign,
    handle_confirm, #确认按钮
    handle_convert, #转换按钮
    handle_shop, #德朗商店
    handle_rest_sortie, #休息/商店入口
    handle_close_button, #关闭按钮
    handle_remove, #移除按钮
    handle_flash, #闪光按钮
    handle_reflash, #重新闪光按钮
    handle_grant_flash, #赋予闪光按钮
    handle_copy, #复制按钮
    handle_leave, #离开按钮
    handle_expedition_result, #探险结果页面，优先级高于下一步
    handle_next_step, #下一步按钮
    handle_select, #选择按钮

    handle_equipment_recast, #装备重铸按钮

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
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_boss_selection,
    handle_get_card,
    handle_card_reward,
    handle_draw_card_event,
    # handle_equipment,
    # handle_mask_card,
    handle_select_card,
    handle_copy_member,
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
    handle_skip,
    handle_event_task,
    handle_rational_supply,
    handle_weakness_info,
    handle_minimizemap,
    handle_held_cards_page,
    handle_escape,
    handle_unknown_page,
]
