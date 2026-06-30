from ok import TriggerTask

import re
import json
import random
import cv2
import numpy as np
from opencc import OpenCC

_cc = OpenCC('t2s')  # 繁转简，用于OCR文本统一转换


def _simplify_texts(texts):
    """将OCR结果的文本批量转换为简体（原地修改）。"""
    for b in texts:
        b.name = _cc.convert(b.name)
    return texts

def _get_config_value(task: TriggerTask, key, default):
    """读取运行时配置，优先从 task.config 读取，其次 default_config，最后使用默认值。"""
    if hasattr(task, 'config') and key in task.config:
        value = task.config[key]
    else:
        value = getattr(task, 'default_config', {}).get(key, default)
    return value


def _get_card_list(task: TriggerTask, key):
    """读取列表配置，解析失败返回空列表。"""
    value = _get_config_value(task, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _get_route_priority(task: TriggerTask):
    """读取路线节点优先级配置，返回列表；解析失败使用默认顺序。"""
    value = _get_config_value(task, '路线优先级', ["休息", "事件", "小怪", "boss"])
    return list(value) if isinstance(value, (list, tuple)) else ["休息", "事件", "小怪", "boss"]


# ------------------------- 通用工具 -------------------------

def find_box_at_point(task: TriggerTask, rel_x, rel_y):
    """查找包含相对坐标点的 box，多个命中时返回面积最小的（最精确）。"""
    px, py = rel_x * task.width, rel_y * task.height
    hits = [b for b in task.all_texts
            if b.x <= px <= b.x + b.width and b.y <= py <= b.y + b.height]
    return min(hits, key=lambda b: b.area()) if hits else None


def find_text(task: TriggerTask, pattern):
    """按正则在所有识别文本中查找第一个匹配的 box。"""
    return next((b for b in task.all_texts if re.search(pattern, b.name)), None)


def find_exact_text(task: TriggerTask, text):
    """查找名称完全等于 text 的第一个 box。"""
    return next((b for b in task.all_texts if b.name == text), None)


def _card_has_type_below(task: TriggerTask, box):
    """判断文本框下方是否有'攻击/强化/技能'类型标签（卡牌名特征）。"""
    box_bottom_y = (box.y + box.height) / task.height
    box_center_x = (box.x + box.width / 2) / task.width
    for b in task.all_texts:
        by = (b.y + b.height / 2) / task.height
        bx = (b.x + b.width / 2) / task.width
        dy = by - box_bottom_y
        # 类型标签可能在卡牌名正下方或略微重叠，允许 -0.005 ~ 0.040
        if -0.005 <= dy <= 0.040:
            if "攻击" in b.name or "强化" in b.name or "技能" in b.name:
                return True
    return False

def select_card(task: TriggerTask, card_names, confirm_point=None, confirm_sleep=1, max_scrolls=5, fallback_delete=False, count=1):
    """依次匹配卡牌名（名称完全相等），点击命中的前 count 张（同一张不会重复选）；可选再点击确认按钮。
    支持向下滚动查找，若滚到底部仍未找到足够数量且 fallback_delete 为 True，则补充点击最后的牌。
    返回成功选择的数量。
    """
    selected = 0
    used = set()  # 记录已选 box 的 (x, y, w, h)，避免同一张牌被重复选择
    for i in range(max_scrolls + 1):
        # 记录当前区域发现的所有卡牌
        found_cards = [b for b in task.all_texts
                       if 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                       and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                       and _card_has_type_below(task, b)]
        if found_cards:
            found_names = [b.name for b in found_cards]
            task.log_info(f"select_card 第{i+1}次查找, 目标: {card_names}, 区域内发现卡牌: {found_names}")

        for name in card_names:
            card = next((b for b in task.all_texts
                         if b.name == name 
                     and 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                     and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                     and (b.x, b.y, b.width, b.height) not in used
                     and _card_has_type_below(task, b)), None)
            if card:
                task.log_info(f"select_card 匹配成功: 名称「{card.name}」, 位置({card.x},{card.y})")
                task.click_box(card)
                used.add((card.x, card.y, card.width, card.height))
                selected += 1
                if selected >= count:
                    if confirm_point:
                        task.sleep(0.5)
                        task.click(*confirm_point)
                        task.sleep(confirm_sleep)
                    return selected
        # 未找到且未达最大次数，向下滚动后重新识别
        if i < max_scrolls:
            task.log_info(f"select_card 第{i+1}次未找到目标, 向下滚动")
            task.scroll_relative(0.5, 0.7, -3)
            task.sleep(0.3)
            task.all_texts = _simplify_texts(task.ocr())

    # fallback: 补充点击当前 OCR 结果里最靠下的卡牌文本，避免固定坐标点到空白
    if fallback_delete and selected < count:
        remaining = count - selected
        task.log_info(f"滚动{max_scrolls}次仍未找到足够目标卡牌，补充点击最后{remaining}张")
        for _ in range(remaining):
            cards = [
                b for b in task.all_texts
                if 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                and b.name not in ["确认", "返回", "跳过"]
                and _card_has_type_below(task, b)
            ]
            if not cards:
                task.log_info("select_card fallback: 区域内无可选卡牌，停止补充")
                break
            fallback_card = max(cards, key=lambda b: (b.y, b.x))
            task.log_info(f"select_card fallback 补充点击: 名称「{fallback_card.name}」, 位置({fallback_card.x},{fallback_card.y})")
            task.click_box(fallback_card)
            selected += 1
            task.sleep(0.3)

    # 已选部分但不足 count，仍点确认
    if selected > 0 and confirm_point:
        task.sleep(0.5)
        task.click(*confirm_point)
        task.sleep(confirm_sleep)
    return selected


def identify_node_type(task: TriggerTask, region, name=""):
    """根据主色相识别路线节点类型，返回节点类型字符串名称。"""
    box = task.box_of_screen(*region, name=f"color_{name}")
    frame = task.frame[box.y:box.y + box.height, box.x:box.x + box.width, :3]
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))

    valid_hue = hue[(sat > 30) & (val > 30)]
    if len(valid_hue) == 0:
        task.log_info(f"节点{name}识别: 无有效色相，判为未知")
        return "未知"

    hist = cv2.calcHist([valid_hue.astype(np.float32)], [0], None, [180], [0, 180])
    dominant_hue = int(np.argmax(hist))
    # 实测色相值: 休息≈18, 事件≈93, boss≈131, 小怪≈169
    # 注意: 102-113 是未知节点，不能归入事件或 boss
    if dominant_hue <= 35:
        result = "休息"
    elif 90 <= dominant_hue <= 100:
        result = "事件"
    elif 120 <= dominant_hue <= 145:
        result = "boss"
    elif dominant_hue >= 150:
        result = "小怪"
    else:
        result = "未知"
    task.log_info(f"节点{name}识别: 主导色相={dominant_hue}, 判为{result}")
    return result


# ------------------------- 页面处理函数 -------------------------
# 约定: 每个函数处理一种页面, 处理成功返回 True, 未命中返回 False。

def log_credit(task: TriggerTask):
    """记录当前信用点数量（仅记录, 不拦截后续处理）。"""
    box = find_box_at_point(task, 0.794, 0.054)
    if box and box.name.isdigit():
        task.log_info(f"当前信用点: {box.name}")
    return False


def handle_battle_auto_check(task: TriggerTask):
    """战斗页面: 检测手牌数并检查自动战斗是否开启，如关闭则开启。"""
    box = find_box_at_point(task, 0.512, 0.969)
    if not (box and re.search(r'\d+/10', box.name)):
        return False

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
        task.click(0.880, 0.056)
        task.sleep(0.5)
    return True


def handle_battle_crash(task: TriggerTask):
    """战斗信息错乱 / 点击重试: 点击屏幕中央恢复。"""
    if find_text(task, r'出现错乱') or find_text(task, r'点击重试'):
        task.log_info("战斗信息出现错乱，点击恢复")
        task.click(0.5, 0.5)
        return True
    return False


def handle_close_page(task: TriggerTask):
    """提示"点击屏幕事件": 点击屏幕。"""
    box = find_text(task, r'点击屏幕')
    if box:
        task.log_info("点击屏幕事件，点击屏幕") 
        task.click_box(box)
        return True
    return False


def handle_center_confirm(task: TriggerTask):
    """页面中央的"确认"按钮。"""
    box = find_box_at_point(task, 0.667, 0.632)
    if box and box.name == "确认":
        task.click(0.667, 0.632)
        return True
    return False


def handle_settlement(task: TriggerTask):
    """"结算"按钮。"""
    box = find_box_at_point(task, 0.941, 0.917)
    if box and box.name == "结算":
        task.click(0.941, 0.917)
        return True
    return False

def handle_skip(task: TriggerTask):
    """"跳过"按钮。"""
    box = find_box_at_point(task, 0.941, 0.917)
    if box and box.name == "跳过":
        task.click_box(box)
        return True
    return False


def handle_destiny_choice(task: TriggerTask):
    """命运选择奖励页面。"""
    box = find_box_at_point(task, 0.499, 0.932)
    if box and re.search(r'请选择你的命运', box.name):
        task.log_info("检测到命运选择奖励，进行相应操作")
        task.click(0.508, 0.487)
        task.sleep(0.5)
        task.click(0.884, 0.931)
        return True
    return False


def handle_main_member_flash(task: TriggerTask):
    """主战员闪光选择页面: 依次选择三个并各自确认。"""
    box = find_box_at_point(task, 0.495, 0.936)
    if box and re.search(r'请选择获得', box.name):
        task.log_info("检测主战员闪光选择，进行相应操作")
        for x, y in [(0.244, 0.446), (0.5, 0.446), (0.748, 0.485)]:
            task.click(x, y)
            task.sleep(1)
            task.click(0.884, 0.931)
            task.sleep(1)
        return True
    return False



def handle_card_reward(task: TriggerTask):
    """卡牌奖励页面: 按卡牌奖励优先级选择卡牌并确认。"""
    box = find_box_at_point(task, 0.498, 0.129)
    if not (box and box.name == "卡牌奖励"):
        return False
    
    task.log_info("检测到卡牌奖励页面")
    priority = _get_card_list(task, "卡牌奖励优先级")

    # 三张卡牌位置
    card_positions = [(0.256, 0.311), (0.499, 0.315), (0.716, 0.314)]
    card_names = []
    for cx, cy in card_positions:
        b = find_box_at_point(task, cx, cy)
        card_names.append(b.name if b else "")

    chosen_idx = None
    for pri_name in priority:
        for i, name in enumerate(card_names):
            if pri_name and name in pri_name:
                chosen_idx = i
                task.log_info(f"按优先级选择卡牌: {name}（配置: {pri_name}）")
                break
        if chosen_idx is not None:
            break

    if chosen_idx is None:
        chosen_idx = random.choice(range(3))
        task.log_info(f"未命中优先级，随机选择卡牌: {card_names[chosen_idx] if card_names[chosen_idx] else '位置' + str(chosen_idx)}")

    cx, cy = card_positions[chosen_idx]
    task.click(cx, cy)
    task.sleep(0.5)
    task.click(0.922, 0.929)
    task.sleep(0.5)
    return True

def handle_equipment(task: TriggerTask):
    """装备选择页面: 依次选择三个装备并确认。"""
    box = find_box_at_point(task, 0.499, 0.126)
    if box and box.name == "装备":
        task.log_info("检测到装备选择，进行相应操作")
        for x, y in [(0.686, 0.736), (0.677, 0.514), (0.692, 0.300)]:
            task.click(x, y)
            task.sleep(0.5)
        task.click(0.884, 0.931)
        task.sleep(2)
        return True
    return False


def handle_mask_card(task: TriggerTask):
    """面具获得卡牌页面: 跳过。"""
    box = find_box_at_point(task, 0.507, 0.090)
    if box and "获得卡牌" in box.name:
        task.log_info("检测获得卡牌选择，进行跳过操作")
        skip_box = find_text(task, r'跳过')
        if skip_box:
            task.click_box(skip_box)
            task.sleep(0.5)
            task.click(0.654, 0.626)
        return True
    return False


def handle_remove_card(task: TriggerTask):
    """移除卡牌页面: 按策略移除指定卡牌，1张或2张，找不到则删最后的牌。"""
    box = find_box_at_point(task, 0.198, 0.039)
    if box and ("请选择1张要移除" in box.name or "请选择2张要移除" in box.name):
        count = 2 if "2张" in box.name else 1
        task.log_info(f"检测获得卡牌移除，需选择{count}张，进行相应操作")
        select_card(task, _get_card_list(task, '移除卡牌列表'), confirm_point=(0.951, 0.932), fallback_delete=True, count=count)
        return True
    return False


def handle_copy_member(task: TriggerTask):
    """选择要复制卡牌的主战员页面。"""
    box = find_box_at_point(task, 0.502, 0.932)
    if box and "选择要复制卡牌的主战员" in box.name:
        task.log_info("检测到卡牌复制主战员选择事件，进行相应操作")
        task.click(0.228, 0.510)
        task.sleep(0.5)
        task.click(0.951, 0.932)
        return True
    return False


def handle_copy_card(task: TriggerTask):
    """请选择要复制的卡牌页面: 按策略选择。"""
    box = find_box_at_point(task, 0.505, 0.131)
    if box and re.search(r"请选择.*要复制的卡牌", box.name):
        task.log_info("检测到卡牌复制选择，进行相应操作")
        select_card(task, _get_card_list(task, '复制卡牌列表'), fallback_delete=True)
        return True
    return False


def handle_flash_card(task: TriggerTask):
    """自选卡牌闪光页面: 按策略选择并确认。"""
    box = find_box_at_point(task, 0.951, 0.932)
    if box and "闪光" in box.name:
        task.log_info("检测到卡牌闪光选择，进行相应操作")
        select_card(task, _get_card_list(task, '闪光卡牌列表'), confirm_point=(0.951, 0.932), fallback_delete=True)
        return True
    return False


def handle_copy_card_pick(task: TriggerTask):
    """自选卡牌复制页面: 按策略选择并确认。"""
    box = find_box_at_point(task, 0.951, 0.932)
    if box and "复制" in box.name:
        task.log_info("检测到卡牌复制选择，进行相应操作")
        select_card(task, _get_card_list(task, '复制卡牌列表'), confirm_point=(0.951, 0.932), fallback_delete=True)
        return True
    return False


def handle_convert_card(task: TriggerTask):
    """转换卡牌页面: 跳过转换。"""
    box = find_box_at_point(task, 0.226, 0.046)
    if box and "转换的卡牌" in box.name:
        task.log_info("检测到卡牌转换选择，进行跳过操作")
        task.click(0.776, 0.926)
        task.sleep(0.5)
        task.click(0.661, 0.632)
        return True
    return False


def handle_negotiation(task: TriggerTask):
    """谈判失败页面: 点击下一步跳过。"""
    title = find_box_at_point(task, 0.498, 0.683)
    if title and title.name in "失败":
        task.log_info("检测到掷骰子失败，跳过掷骰子")
        task.click(0.665, 0.899)
        return True
    return False


def handle_continue(task: TriggerTask):
    """通用"继续"按钮。"""
    box = find_exact_text(task, "继续")
    if box:
        task.log_info("检测到下一步操作，点击继续")
        task.click_box(box)
        return True
    return False


def handle_confirm(task: TriggerTask):
    """通用"确认"按钮。"""
    box = find_exact_text(task, "确认")
    if box:
        task.log_info("检测到确认操作，点击确认")
        task.click_box(box)
        return True
    return False


def handle_enter(task: TriggerTask):
    """通用"进入"按钮。"""
    box = find_exact_text(task, "进入")
    if box:
        task.log_info("检测到进入按钮，点击进入")
        task.click_box(box)
        return True
    return False


def group_dialog_columns(task: TriggerTask, region, max_width_ratio=0.25, align_tolerance=0.04):
    """把区域内的窄文本框按左边缘对齐关系聚成对话框列, 返回每列的中心 x 坐标及文本列表。

    返回格式: [{'x': 中心x(相对), 'texts': [文本1, 文本2, ...]}, ...]
    - region: (x1, y1, x2, y2) 相对坐标, 仅统计中心落在其中的文本框。
    - max_width_ratio: 过滤过宽文本(如剧情旁白), 避免和对话框选项混淆。
    - align_tolerance: 左边缘差值在此范围内视为同一列(同一个对话框)。
    """
    x1, y1, x2, y2 = region
    boxes = [b for b in task.all_texts
             if x1 <= (b.x + b.width / 2) / task.width <= x2
             and y1 <= (b.y + b.height / 2) / task.height <= y2
             and b.width / task.width <= max_width_ratio
             and len(b.name) > 2]
    columns = []  # 每列: {'left': 左边缘, 'centers': [中心x, ...], 'texts': [文本, ...]}
    for box in sorted(boxes, key=lambda b: b.x):
        left = box.x / task.width
        center = (box.x + box.width / 2) / task.width
        if columns and left - columns[-1]['left'] <= align_tolerance:
            columns[-1]['centers'].append(center)
            columns[-1]['texts'].append(box.name)
        else:
            columns.append({'left': left, 'centers': [center], 'texts': [box.name]})
    return [{'x': sum(c['centers']) / len(c['centers']), 'texts': c['texts']} for c in columns]


def handle_event_task(task: TriggerTask):
    """事件任务页面: 识别标题+描述区域，按任务优先级匹配描述选择推进。"""
    # 先检查任务奖励图标
    rewards = task.find_feature(feature_name="taskreward")
    if rewards:
        reward = rewards[0]
        cx = (reward.x + reward.width / 2) / task.width
        cy = (reward.y + reward.height / 2) / task.height
        if 0.437 <= cx <= 0.902 and 0.350 <= cy <= 0.614:
            task.log_info("检测到任务奖励图标，优先点击")
            task.click_box(reward)
            return True

    # 排除非任务页面: 若底部有 "x/10" 文本则不是任务页面
    bottom_box = find_box_at_point(task, 0.516, 0.971)
    if bottom_box and re.search(r'\d+/\d+', bottom_box.name):
        # task.log_debug(f"handle_event_task: 底部检测到数字({bottom_box.name})，不是任务页面")
        return False

    # 在标题区域(0.121, 0.769, 0.844, 0.818)查找宽度<0.232的文本
    px1, py1 = int(0.121 * task.width), int(0.769 * task.height)
    px2, py2 = int(0.844 * task.width), int(0.818 * task.height)

    candidates = [
        b for b in task.all_texts
        if b.x >= px1 and b.y >= py1 and b.x + b.width <= px2 and b.y + b.height <= py2
        and (b.width / task.width) < 0.232
        and len(b.name.strip()) > 1
        and b.name not in ["确认", "返回", "跳过"]
    ]

    if not (1 <= len(candidates) <= 3):
        # task.log_debug(f"handle_event_task: 标题区域候选文本数={len(candidates)}，不在1~3范围")
        return False

    # 按 y 分组（同一行），取最多文本的那一行作为标题行
    candidates.sort(key=lambda b: (b.y, b.x))
    rows = []
    current_row = [candidates[0]]
    for b in candidates[1:]:
        if abs(b.y - current_row[-1].y) < task.height * 0.02:
            current_row.append(b)
        else:
            rows.append(current_row)
            current_row = [b]
    rows.append(current_row)
    titles = max(rows, key=len)

    if not (1 <= len(titles) <= 3):
        # task.log_debug(f"handle_event_task: 分组后标题数={len(titles)}，不在1~3范围")
        return False

    # 检查每个标题下方是否有描述文本
    tasks_info = []
    for title in titles:
        desc_left = title.x
        desc_top = title.y + title.height
        desc_right = title.x + 0.221 * task.width
        desc_bottom = title.y + title.height + 0.121 * task.height

        desc_lines = [
            b for b in task.all_texts
            if b.x >= desc_left - 0.01 * task.width and b.y >= desc_top
            and b.x + b.width <= desc_right + 0.01 * task.width and b.y + b.height <= desc_bottom
            and b.name not in ["确认", "返回", "跳过"]
        ]

        if not desc_lines:
            # task.log_debug(f"handle_event_task: 标题「{title.name}」下方无描述文本")
            return False

        desc_lines.sort(key=lambda b: b.y)
        desc_text = "".join(b.name.strip() for b in desc_lines)

        tasks_info.append({
            'x': (title.x + title.width / 2) / task.width,
            'title': title.name,
            'description': desc_text
        })

    task.log_info(f"检测到事件任务({len(tasks_info)}个选项):")
    for t in tasks_info:
        task.log_info(f"  标题: {t['title']} | 描述: {t['description']}")

    # 按任务优先级匹配描述
    priority = _get_config_value(task, '任务优先级', [])
    chosen = None
    for keyword in priority:
        for t in tasks_info:
            if keyword in t['description']:
                chosen = t
                task.log_info(f"优先选择「{keyword}」-> 标题: {t['title']}, 描述: {t['description']}")
                break
        if chosen is not None:
            break

    if chosen is None:
        chosen = random.choice(tasks_info)
        task.log_info(f"未命中优先级描述，随机选择: {chosen['title']}")

    chosen_x = chosen['x']
    task.click(chosen_x, 0.832)
    task.sleep(1)
    task.click(chosen_x, 0.952)
    task.sleep(1)
    return True

def handle_route_selection(task: TriggerTask):
    """路线选择页面: 识别节点类型，按优先级排序后依次点击所有节点，每次间隔1秒。"""
    position_feature = task.find_feature(feature_name="position")
    cant_receive = find_box_at_point(task, 0.186, 0.850)
    is_route_page = position_feature or (cant_receive and "无法接收到梦境号" in cant_receive.name)
    if not is_route_page:
        return False
    task.log_info("检测到路线选择页面，按优先级依次点击节点")
    task.sleep(2)
    node_regions = {
        "node1": (0.759, 0.168, 0.769, 0.186),
        "node2": (0.901, 0.471, 0.910, 0.486),
        "node3": (0.758, 0.765, 0.769, 0.781),
    }
    click_points = {
        "node1": (0.666, 0.232),
        "node2": (0.805, 0.512),
        "node3": (0.664, 0.801),
    }

    node_types = {k: identify_node_type(task, r, name=k) for k, r in node_regions.items()}
    priority = _get_route_priority(task)
    task.log_info(f"路线优先级配置: {priority}")
    task.log_info(f"识别到的节点类型: {node_types}")

    # 按优先级排序节点（优先级高的在前），同优先级保持原始顺序
    def sort_key(item):
        node_type = item[1]
        try:
            return priority.index(node_type)
        except ValueError:
            return len(priority)  # 未配置的优先级排最后

    sorted_nodes = sorted(node_types.items(), key=sort_key)

    for node_key, node_type in sorted_nodes:
        task.log_info(f"点击节点{node_key[-1]} (类型: {node_type})")
        task.click(*click_points[node_key])
        task.sleep(1)

    return True


def handle_obtain_reward(task: TriggerTask):
    """获得奖励页面: 点击领取。"""
    box = find_box_at_point(task, 0.924, 0.922)
    if box and box.name == "获得":
        task.log_info("检测到获得奖励页面，点击领取")
        task.click_box(box)
        return True
    return False


def handle_leave(task: TriggerTask):
    """离开按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and box.name == "离开":
        task.log_info("检测到离开按钮，点击离开")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_rest(task: TriggerTask):
    """休息界面: 优先休息，然后进入德朗商店"""
    box = find_box_at_point(task, 0.323, 0.733)
    if box and box.name == "休息":
        task.log_info("检测休息界面，点击休息")
        task.click_box(box)
        task.sleep(0.5)
        task.click(0.568, 0.669) #确认休息
        task.sleep(0.5)
    
    if _get_config_value(task, "进入商店", False):
        shop_box = find_box_at_point(task, 0.366, 0.133)
        if shop_box and shop_box.name == "德朗商店":
            task.log_info("检测休息界面，发现德朗商店，进入")
            task.click_box(shop_box)
            return True
    return False


def handle_shop(task: TriggerTask):
    """德朗商店: 若信用点足够则点击移除卡牌。"""
    # task.log_info("handle_shop: 进入德朗商店处理")
    box = find_box_at_point(task, 0.729, 0.261)
    soldout = find_box_at_point(task, 0.727, 0.286)
    # task.log_info(f"handle_shop: 0.729,0.261处文本='{box.name if box else None}', 0.727,0.286处文本='{soldout.name if soldout else None}'")
    if (box and box.name == "移除卡牌") or (soldout and soldout.name in ["售罄","售馨"]):
        task.log_info("handle_shop: 通过页面判定（移除卡牌或售罄）")
        if soldout and soldout.name in ["售罄","售馨"]:
            task.log_info(f"德朗商店: 移除卡牌已售罄")
            task.click(0.948, 0.935) #点击离开商店
            task.sleep(1)
            task.click(0.941, 0.918) #点击离开篝火
            task.sleep(1)
            return True
        # 获取当前信用点
        credit_box = find_box_at_point(task, 0.794, 0.054)
        task.log_info(f"handle_shop: 0.794,0.054处信用点文本='{credit_box.name if credit_box else None}'")
        if not (credit_box and credit_box.name.isdigit()):
            task.log_info("handle_shop: 信用点读取失败，return False")
            return False
        current_credit = int(credit_box.name)

        # 获取移除卡牌所需信用点
        cost_box = find_box_at_point(task, 0.724, 0.319)
        task.log_info(f"handle_shop: 0.724,0.319处费用文本='{cost_box.name if cost_box else None}'")
        if not (cost_box and cost_box.name.isdigit()):
            task.log_info("handle_shop: 费用读取失败，return False")
            return False
        cost = int(cost_box.name)
        if cost < current_credit:
            task.log_info(f"德朗商店: 移除卡牌需{cost}信用点，当前{current_credit}，足够，点击移除")
            task.click_box(box)
            return True
        else:
            task.log_info(f"德朗商店: 移除卡牌需{cost}信用点，当前{current_credit}，不足，跳过")
            task.click(0.948, 0.935) #点击离开商店
            task.sleep(1)
            task.click(0.941, 0.918) #点击离开篝火
            task.sleep(1)
            return True
    # task.log_info("handle_shop: 未检测到移除卡牌或售罄，return False")
    return False

def _cluster_region_boxes(task: TriggerTask, region):
    """将区域内文本框按 x 坐标聚类为列（用于卡牌名/效果描述区域），返回 [{'x': 中心x, 'texts': [...]}, ...]"""
    x1, y1, x2, y2 = region
    boxes = [b for b in task.all_texts
             if x1 <= (b.x + b.width / 2) / task.width <= x2
             and y1 <= (b.y + b.height / 2) / task.height <= y2]
    columns = []
    for box in sorted(boxes, key=lambda b: b.x):
        cx = (box.x + box.width / 2) / task.width
        if columns and abs(cx - columns[-1]['x']) <= 0.08:
            columns[-1]['texts'].append(box.name)
        else:
            columns.append({'x': cx, 'texts': [box.name]})
    return columns


def handle_view_original(task: TriggerTask):
    """卡牌闪光（查看原件）事件: 聚类卡牌名和效果描述，按 FLASH_PRIORITY 优先选择。

    - 卡牌名区域: (0.148, 0.192, 0.859, 0.325)
    - 效果描述区域: (0.154, 0.456, 0.859, 0.786)
    """
    box1 = find_box_at_point(task, 0.890, 0.051)
    box2 = find_box_at_point(task, 0.896, 0.131)
    if not ((box1 and box1.name == "查看原件") or (box2 and box2.name == "查看原件")):
        return False

    name_cols = _cluster_region_boxes(task, (0.148, 0.192, 0.859, 0.325))
    desc_cols = _cluster_region_boxes(task, (0.154, 0.456, 0.859, 0.786))

    if not name_cols or not desc_cols:
        return False

    # 按 x 坐标匹配 name 列和 desc 列（通常 3 张卡牌各一列）
    cards = []
    for name_col in name_cols:
        # 找最近的 desc 列
        nearest_desc = min(desc_cols, key=lambda d: abs(d['x'] - name_col['x']))
        # 卡牌名只取该列第一行（最上面），不合并其他行（如"攻击"/"强化"等类型标签）
        card_name = name_col['texts'][0] if name_col['texts'] else ''
        cards.append({
            'x': (name_col['x'] + nearest_desc['x']) / 2,
            'name': card_name,
            'descs': nearest_desc['texts'],
        })

    # 输出结构化日志
    log_parts = [f"检测到卡牌闪光事件，卡牌名称是{cards[0]['name']}"]
    for i, card in enumerate(cards, 1):
        log_parts.append(f"闪光{i}效果是{'、'.join(card['descs'])}")
    task.log_info('，'.join(log_parts))

    # 按 闪光优先级 配置优先选择
    flash_priority = _get_config_value(task, '闪光优先级', {})
    if isinstance(flash_priority, str):
        try:
            flash_priority = json.loads(flash_priority)
        except json.JSONDecodeError:
            flash_priority = {}
    chosen_card = None
    for card_name, priority_descs in flash_priority.items():
        for card in cards:
            if card_name not in card['name']:
                continue
            for desc_keyword in priority_descs:
                if any(desc_keyword in d for d in card['descs']):
                    chosen_card = card
                    task.log_info(f"优先选择「{card['name']}」({desc_keyword})")
                    break
            if chosen_card:
                break
        if chosen_card:
            break

    if not chosen_card:
        chosen_card = random.choice(cards)
        task.log_info(f"随机选择「{chosen_card['name']}」")

    task.click(chosen_card['x'], 0.515)
    return True


def handle_battle_failed(task: TriggerTask):
    """战斗失败页面: 点击下一步。"""
    box = find_box_at_point(task, 0.291, 0.718)
    if box and box.name == "战斗失败":
        task.log_info("检测到战斗失败，建议降低难度")
        task.click(0.905, 0.917)
        return True
    return False


def handle_data_collected(task: TriggerTask):
    """存储数据收集完成页面: 点击下一步。"""
    box = find_box_at_point(task, 0.505, 0.111)
    if box and box.name == "存储数据收集完成":
        task.log_info("检测到存储数据收集完成，下一步")
        task.click(0.905, 0.917)
        return True
    return False


def handle_mental_breakdown(task: TriggerTask):
    """精神崩溃发生页面: 前往创伤中心。"""
    box = find_box_at_point(task, 0.496, 0.186)
    if box and box.name == "精神崩溃发生":
        task.log_info("检测到精神崩溃发生，去创伤中心")
        task.click(0.706, 0.915)
        return True
    return False


def handle_trauma_center(task: TriggerTask):
    """创伤中心: 优先使用金币治疗。"""
    box = find_box_at_point(task, 0.125, 0.049)
    if not (box and "创伤中心" in box.name):
        return False
    task.log_info("检测到创伤中心")

    # 没有恢复中的战员
    no_recover = find_box_at_point(task, 0.583, 0.726)
    if no_recover and "没有恢复中的战员" in no_recover.name:
        task.click(0.044, 0.046)
        task.sleep(1)
        return True

    task.click(0.420, 0.339)
    task.sleep(0.5)

    prefer_gold = _get_config_value(task, "优先使用金币治疗", True)
    travel_ticket = task.ocr(0.933, 0.904, 0.971, 0.943)
    if travel_ticket:
        has_ticket = int(travel_ticket[0].name[0]) > 0
        if prefer_gold or not has_ticket:
            task.click(0.702, 0.924)
        else:
            task.click(0.798, 0.924)
        task.sleep(0.5)
    return True


def handle_explore_result(task: TriggerTask):
    """探险结果页面: 点击关闭。"""
    box = find_box_at_point(task, 0.623, 0.115)
    if box and box.name == "探险结果":
        task.click(0.916, 0.915)
        return True
    return False


def handle_treating(task: TriggerTask):
    """治疗进行中页面: 选择治疗方法。"""
    if find_text(task, r'选择哪种方法进行治疗'):
        task.log_info("检测到治疗进行中")
        task.click(0.765, 0.500)
        return True
    return False


def handle_treat_approve(task: TriggerTask):
    """治疗完成页面: 点击批准。"""
    if find_text(task, r'点击批准'):
        task.log_info("检测到治疗完成，点击批准")
        task.click(0.768, 0.810)
        return True
    return False




def handle_discovery_select(task: TriggerTask):
    """发现选择页面: 随机选择一个发现并确认。"""
    title = find_box_at_point(task, 0.498, 0.078)
    confirm = find_box_at_point(task, 0.880, 0.921)
    if not (title and title.name == "获得法典" and confirm and confirm.name == "确认"):
        return False

    task.log_info("检测到发现选择页面，随机选择一项")
    positions = [(0.180, 0.519), (0.505, 0.514), (0.818, 0.519)]
    chosen = random.choice(positions)
    task.click(*chosen)
    task.sleep(0.3)
    task.click_box(confirm)
    task.sleep(1)
    return True



def handle_zero_system_home(task: TriggerTask):
    """零式系统首页: 点击法典。"""
    title = find_box_at_point(task, 0.120, 0.046)
    codex = find_box_at_point(task, 0.812, 0.469)
    if title and title.name == "零式系统" and codex and codex.name == "法典":
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
    task.click(0.5, 0.760)
    task.sleep(2)
    return True


def handle_cares_tip(task: TriggerTask):
    """卡厄思 TIP 提示页面: 点击关闭。"""
    box = find_box_at_point(task, 0.502, 0.286)
    if box and box.name == "TIP":
        task.click(0.884, 0.915)
        return True
    return False


def handle_close_button(task: TriggerTask):
    """通用关闭按钮: 检测到关闭按钮则点击关闭。"""
    box = find_box_at_point(task, 0.512, 0.929)
    if box and box.name == "关闭":
        task.log_info("检测到关闭按钮，点击关闭")
        task.click_box(box)
        return True
    return False


def handle_memory_elimination(task: TriggerTask):
    """记忆消除页面: 点击记忆消除按钮。"""
    box = find_box_at_point(task, 0.589, 0.703)
    if box and box.name == "记忆消除":
        task.log_info("检测到记忆消除页面，点击记忆消除")
        task.click_box(box)
        task.sleep(0.5)
        return True
    return False

def handle_card_assign(task: TriggerTask):
    """卡牌分配页面: 随机选择一个主战员接受卡牌（优先级高于卡牌奖励页面）。"""
    box = find_box_at_point(task, 0.863, 0.133)
    if not (box and "请选择要接受卡牌的主战员" in box.name):
        return False

    task.log_info("检测到卡牌分配页面")

    # 在区域内查找所有"防御力"文本（精确匹配），每个代表一个主战员
    px1, py1 = int(0.727 * task.width), int(0.206 * task.height)
    px2, py2 = int(0.786 * task.width), int(0.742 * task.height)

    def_texts = sorted(
        [b for b in task.all_texts
         if b.x >= px1 and b.y >= py1 and b.x + b.width <= px2 and b.y + b.height <= py2
         and b.name in "防御力"],
        key=lambda b: b.y
    )

    if not def_texts:
        task.log_info("未找到主战员防御力信息")
        return False

    count = len(def_texts)
    chosen_idx = random.randint(0, count - 1)
    chosen_def = def_texts[chosen_idx]
    task.log_info(f"共{count}个主战员，随机选择第{chosen_idx + 1}号")

    # 点击选中的主战员
    task.click(0.756, (chosen_def.y + chosen_def.height / 2) / task.height)
    task.sleep(0.3)
    task.click(0.919, 0.933)
    task.sleep(0.5)
    return True


def handle_expedition_unlock(task: TriggerTask):
    """解锁探险记录页面: 点击确定。"""
    box = find_box_at_point(task, 0.5, 0.151)
    if box and re.search(r"解锁的探险记录将会在.*", box.name):
        task.log_info("检测到解锁探险记录页面，点击确定")
        task.click(0.5, 0.8)
        task.sleep(1)
        return True
    return False


def handle_non_battle_page(task: TriggerTask):
    """非出击/卡厄思页面: 检测到故事/营救/方舟城市时自动停止当前模式，优先级最高。"""
    box = find_box_at_point(task, 0.887, 0.160)
    if box and box.name == "故事":
        task.log_info("检测到故事页面，停止当前模式")
        task.disable()
        return True
    box = find_box_at_point(task, 0.101, 0.046)
    if box and box.name == "营救":
        task.log_info("检测到营救页面，停止当前模式")
        task.disable()
        return True
    box = find_box_at_point(task, 0.124, 0.049)
    if box and box.name == "方舟城市":
        task.log_info("检测到方舟城市页面，停止当前模式")
        task.disable()
        return True
    return False


# 处理函数按优先级排序; run() 依次尝试, 命中即停止。
PAGE_HANDLERS = [
    log_credit,
    handle_non_battle_page,
    handle_battle_crash,
    handle_battle_auto_check,
    handle_close_page,
    handle_center_confirm,
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_card_assign,
    handle_card_reward,
    handle_equipment,
    handle_mask_card,
    handle_remove_card,
    handle_copy_member,
    handle_copy_card,
    handle_flash_card,
    handle_copy_card_pick,
    handle_convert_card,
    handle_discovery_select,
    handle_negotiation,
    handle_continue,
    handle_confirm,
    handle_enter,
    handle_route_selection,
    handle_obtain_reward,
    handle_rest,
    handle_shop,
    handle_view_original,
    handle_battle_failed,
    handle_data_collected,
    handle_mental_breakdown,
    handle_trauma_center,
    handle_explore_result,
    handle_treating,
    handle_treat_approve,
    handle_zero_system_home,
    handle_codex_search,
    handle_expedition_unlock,
    handle_cares_tip,
    handle_memory_elimination,
    handle_leave,
    handle_skip,
    handle_event_task,
    handle_close_button,
]
