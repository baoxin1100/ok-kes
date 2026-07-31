from ok import TriggerTask

import re
import json
import random
import time
import cv2
import os
import numpy as np
from opencc import OpenCC

_cc = OpenCC('t2s')  # 繁转简，用于OCR文本统一转换


def _edit_distance(s1, s2, max_dist=1):
    """计算两个字符串的编辑距离是否 <= max_dist。"""
    if abs(len(s1) - len(s2)) > max_dist:
        return False
    if not s1 or not s2:
        return max(len(s1), len(s2)) <= max_dist
    m, n = len(s1), len(s2)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n] <= max_dist


def is_subsequence(first: str, second: str) -> bool:
    """判断第一个字符串是否为第二个字符串的子序列。"""
    second_iter = iter(second)
    return all(char in second_iter for char in first)


def _simplify_texts(texts):
    """将OCR结果的文本批量转换为简体（原地修改）。"""
    for b in texts:
        b.name = _cc.convert(b.name)
    return texts


def _get_config_value(task: TriggerTask, key, default):
    """读取运行时配置，优先从 task.config 读取，其次 default_config，最后使用默认值。返回前将字符串转简体。"""
    if hasattr(task, 'config') and key in task.config:
        value = task.config[key]
    else:
        value = getattr(task, 'default_config', {}).get(key, default)
    if isinstance(value, str):
        value = _cc.convert(value)
    elif isinstance(value, (list, tuple)):
        value = [_cc.convert(v) if isinstance(v, str) else v for v in value]
    return value


def _get_card_list(task: TriggerTask, key):
    """读取列表配置，解析失败返回空列表。"""
    value = _get_config_value(task, key, [])
    return list(value) if isinstance(value, (list, tuple)) else []


def _get_card_reward_priority(task: TriggerTask):
    """读取卡牌奖励优先级，并将刷初始卡牌配置置于最高优先级。"""
    priority = _get_card_list(task, "卡牌奖励优先级")
    initial_card_name = _get_config_value(task, "刷初始卡牌", "")
    initial_card_name = initial_card_name.strip() if isinstance(initial_card_name, str) else ""
    if initial_card_name:
        priority = [
            initial_card_name,
            *(name for name in priority if name != initial_card_name),
        ]
    return priority


# 游戏语言 → 映射文件路径
_GAME_LANG_FILE_MAP = {
    "繁体中文": os.path.join(os.path.dirname(__file__), 'assets', 'game_text_map', 'zh_tw.py'),
}
# 已加载的映射缓存 {语言: SERVER_TEXT_MAP字典}
_LOADED_MAPS = {}


def _load_game_text_map(game_lang):
    """加载指定语言的映射表（带缓存）。"""
    if game_lang not in _LOADED_MAPS:
        file_path = _GAME_LANG_FILE_MAP.get(game_lang)
        if file_path and os.path.exists(file_path):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(f"_game_map_{game_lang}", file_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _LOADED_MAPS[game_lang] = getattr(mod, 'SERVER_TEXT_MAP', {})
            except Exception:
                _LOADED_MAPS[game_lang] = {}
        else:
            _LOADED_MAPS[game_lang] = {}
    return _LOADED_MAPS[game_lang]


def _get_game_text(task: TriggerTask, default_text):
    """根据全局配置的游戏语言，返回对应服务器版本的搜索文本。
    
    用户在工具左下角 Settings → Game Language Config 中设置，
    无需在每个任务中单独配置。
    """
    try:
        lang_config = task.executor.global_config.get_config('游戏语言')
        game_lang = lang_config.get('游戏语言', '简体中文')
    except Exception:
        game_lang = '简体中文'

    if game_lang == '简体中文':
        return default_text

    mapping = _load_game_text_map(game_lang)
    return mapping.get(default_text, default_text)


def _migrate_route_boss_to_elite(task: TriggerTask):
    """迁移用户配置中"路线优先级"的"boss"为"精英"（兼容旧配置）。"""
    try:
        if hasattr(task, 'config') and '路线优先级' in task.config:
            priority = task.config['路线优先级']
            if isinstance(priority, (list, tuple)):
                new_priority = ["精英" if v == "boss" else v for v in priority]
                if new_priority != list(priority):
                    task.config['路线优先级'] = new_priority
                    from ok.gui.Communicate import communicate
                    communicate.task_list_updated.emit()
                    task.log_info(f"迁移路线优先级配置: boss→精英 {new_priority}")
    except Exception:
        pass


def _get_route_priority(task: TriggerTask):
    """读取路线节点优先级配置，返回列表；解析失败使用默认顺序。"""
    value = _get_config_value(task, '路线优先级', ["休息", "事件", "小怪", "精英"])
    return list(value) if isinstance(value, (list, tuple)) else ["休息", "事件", "小怪", "精英"]


# ------------------------- 通用工具 -------------------------

def _get_current_credit(task: TriggerTask):
    """读取当前信用点数，从两个可能位置取最大值。"""
    credit = 0
    for pos_x, pos_y in [(0.794, 0.054), (0.734, 0.053)]:
        box = find_box_at_point(task, pos_x, pos_y)
        if box and box.name.isdigit():
            val = int(box.name)
            if val > credit:
                credit = val
    return credit


def _get_current_hp_percent(task: TriggerTask):
    """读取当前生命值百分比，无法识别时返回 False。"""
    hp_box = find_box_at_point(task, 0.209, 0.040)
    if not hp_box:
        return False
    hp_match = re.search(r'(\d+)/(\d+)', hp_box.name)
    if not hp_match:
        return False
    current_hp = int(hp_match.group(1))
    max_hp = int(hp_match.group(2))
    if max_hp <= 0:
        return False
    hp_percent = int(current_hp * 100 / max_hp)
    task.log_info(f"当前生命值: {current_hp}/{max_hp} = {hp_percent}%")
    return hp_percent


def find_box_at_point(task: TriggerTask, rel_x, rel_y):
    """查找包含相对坐标点的 box，多个命中时返回面积最小的（最精确）。"""
    px, py = rel_x * task.width, rel_y * task.height
    hits = [b for b in task.all_texts
            if b.x <= px <= b.x + b.width and b.y <= py <= b.y + b.height]
    return min(hits, key=lambda b: b.area()) if hits else None


def find_target_card(task: TriggerTask):
    """查找target卡牌特征，返回特征框列表及其对应的相对点击位置。"""
    search_box = task.box_of_screen(0.090, 0.179, 0.927, 0.342)
    target_boxes = task.find_feature(feature_name="target", box=search_box) or []
    click_positions = []
    for target_box in target_boxes:
        center_x = (target_box.x + target_box.width / 2) / task.width
        center_y = (target_box.y + target_box.height / 2) / task.height
        click_positions.append((
            min(1.0, max(0.0, center_x - 0.0975)),
            min(1.0, max(0.0, center_y + 0.2460)),
        ))
    return target_boxes, click_positions


def find_text(task: TriggerTask, pattern):
    """按正则在所有识别文本中查找第一个匹配的 box。"""
    return next((b for b in task.all_texts if re.search(pattern, b.name)), None)


def find_exact_text(task: TriggerTask, text):
    """查找名称（清理符号后）完全等于 text 的第一个 box。"""
    return next((b for b in task.all_texts if _clean_match(b.name, text)), None)


def _clean_match(name, target):
    """去除OCR文本中的非中文/字母/数字符号后比较是否等于 target。"""
    cleaned = re.sub(r'[^\u4e00-\u9fff\w]', '', name)
    return cleaned == target


def _get_region_text(task: TriggerTask, region):
    """获取指定区域内所有OCR文本，去除空白后用"".join拼接返回。"""
    x1, y1, x2, y2 = region
    texts = [
        b.name.strip() for b in task.all_texts
        if x1 <= (b.x + b.width / 2) / task.width <= x2
        and y1 <= (b.y + b.height / 2) / task.height <= y2
        and b.name.strip()
    ]
    return "".join(texts)


def _is_valid_card_name(name):
    """过滤非卡牌名的文本：单个字母、单个符号、纯符号等都不是卡牌名。"""
    if len(name.strip()) <= 1:
        return False
    # 排除纯符号/特殊字符组成的名（不含中文字符和字母）
    if not re.search(r'[\u4e00-\u9fff\w]', name):
        return False
    return True


_CARD_TYPE_KEYWORDS = {
    "攻击", "强化", "技能", "技", "咒术", "诅咒",
    "攻", "击", "基础", "基本", "状态", "异常",
}


def _card_has_type_below(task: TriggerTask, box):
    """判断文本框下方是否有卡牌类型标签（卡牌名特征）。"""
    box_bottom_y = (box.y + box.height) / task.height
    box_cx = (box.x + box.width / 2) / task.width
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        dy = cy - box_bottom_y
        dx = abs(cx - box_cx)
        if -0.005 <= dy <= 0.040 and dx <= 0.045 and len(b.name) <= 4:
            for kw in _CARD_TYPE_KEYWORDS:
                if kw in b.name:
                    return True
    return False


def _card_has_base_type_below(task: TriggerTask, box):
    """判断卡牌下方的类型标签是否包含'基础'或'基本'。"""
    box_bottom_y = (box.y + box.height) / task.height
    box_cx = (box.x + box.width / 2) / task.width
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        dy = cy - box_bottom_y
        dx = abs(cx - box_cx)
        if -0.005 <= dy <= 0.040 and dx <= 0.045 and len(b.name) <= 4:
            if "基础" in b.name or "基本" in b.name:
                return True
    return False


def select_card(task: TriggerTask, card_names, max_scrolls=5, fallback_delete=False, count=1, action=""):
    """依次匹配卡牌名（子串包含匹配），点击命中的前 count 张（同一张不会重复选）。
    支持向下滚动查找，若滚到底部仍未找到足够数量且 fallback_delete 为 True，则补充点击最后的牌。
    当 action 为 "移除" 且配置"优先移除基础牌"为 True 时，兜底优先选择类型含"基础"的卡牌。
    返回成功选择的数量。
    """
    selected = 0
    used_positions = []

    # 判断是否需要在移除删除时优先选择基础牌
    is_remove_priority_base = False
    if action == "移除":
        is_remove_priority_base = _get_config_value(task, "优先移除基础牌", True)

    for i in range(max_scrolls + 1):
        found_cards = [b for b in task.all_texts
                       if 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                       and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                       and _is_valid_card_name(b.name)
                       and _card_has_type_below(task, b)]
        if found_cards:
            found_names = [b.name for b in found_cards]
            task.log_info(f"select_card 第{i+1}次查找, 目标: {card_names}, 区域内发现卡牌: {found_names}")

        for name in card_names:
            card = next((b for b in task.all_texts
                         if (
                             b.name == name
                             if action == "移除" and is_remove_priority_base
                             else name in b.name or b.name in name
                         )
                     and 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                     and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                     and not any(abs(ux - b.x) <= 10 and abs(uy - b.y) <= 10 for ux, uy, _, _ in used_positions)
                     and _card_has_type_below(task, b)), None)
            if card:
                task.log_info(f"select_card 匹配成功: 名称「{card.name}」, 位置({card.x},{card.y})")
                task.click_box(card)
                used_positions.append((card.x, card.y, card.width, card.height))
                selected += 1
                if selected >= count:
                    return selected
        if i < max_scrolls:
            task.log_info(f"select_card 第{i+1}次未找到目标, 向下滚动")
            task.scroll_relative(0.5, 0.7, -3)
            task.sleep(0.3)
            task.all_texts = _simplify_texts(task.ocr())

    if fallback_delete and selected < count:
        remaining = count - selected
        task.log_info(f"滚动{max_scrolls}次仍未找到足够目标卡牌，补充点击最后{remaining}张")
        for _ in range(remaining):
            task.all_texts = _simplify_texts(task.ocr())
            cards = [
                b for b in task.all_texts
                if 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                and not any(abs(ux - b.x) <= 10 and abs(uy - b.y) <= 10 for ux, uy, _, _ in used_positions)
                and b.name not in ["确认", "返回", "跳过"]
                and _is_valid_card_name(b.name)
                and _card_has_type_below(task, b)
            ]
            # 如果是移除操作且启用了优先移除基础牌
            if is_remove_priority_base:
                # 先从当前区域找基础牌（从后往前优先）
                base_card = next((c for c in reversed(cards) if _card_has_base_type_below(task, c)), None)
                if base_card:
                    fallback_card = base_card
                    task.log_info(f"select_card fallback 优先选择基础牌: 「{base_card.name}」")
                else:
                    task.log_info("select_card fallback: 移除操作且当前区域无基础牌，向上翻找")
                    for up_i in range(max_scrolls):
                        task.scroll_relative(0.5, 0.7, 3)
                        task.sleep(0.3)
                        task.all_texts = _simplify_texts(task.ocr())
                        up_cards = [
                            b for b in task.all_texts
                            if 0.274 <= (b.x + b.width / 2) / task.width <= 0.931
                            and 0.106 <= (b.y + b.height / 2) / task.height <= 0.878
                            and not any(abs(ux - b.x) <= 10 and abs(uy - b.y) <= 10 for ux, uy, _, _ in used_positions)
                            and b.name not in ["确认", "返回", "跳过"]
                            and _is_valid_card_name(b.name)
                            and _card_has_type_below(task, b)
                        ]
                        base_card = next((c for c in reversed(up_cards) if _card_has_base_type_below(task, c)), None)
                        if base_card:
                            task.log_info(f"select_card fallback 向上翻找到基础牌: 「{base_card.name}」")
                            task.click_box(base_card)
                            used_positions.append((base_card.x, base_card.y, base_card.width, base_card.height))
                            selected += 1
                            task.sleep(0.3)
                            break
                    else:
                        # 向上翻完还没找到基础牌，用回原来兜底逻辑
                        if not cards:
                            task.log_info("select_card fallback: 上翻后无基础牌且原区域无卡牌，停止补充")
                            break
                        fallback_card = max(cards, key=lambda b: (b.y, b.x))
                        task.log_info(f"select_card fallback 上翻未找到基础牌，回退选择: 「{fallback_card.name}」")
                        task.click_box(fallback_card)
                        used_positions.append((fallback_card.x, fallback_card.y, fallback_card.width, fallback_card.height))
                        selected += 1
                        task.sleep(0.3)
                    continue
            else:
                # 非移除操作，用原有兜底
                if not cards:
                    task.log_info("select_card fallback: 区域内无可选卡牌，停止补充")
                    break
                fallback_card = max(cards, key=lambda b: (b.y, b.x))
            task.log_info(f"select_card fallback 补充点击: 名称「{fallback_card.name}」, 位置({fallback_card.x},{fallback_card.y})")
            task.click_box(fallback_card)
            used_positions.append((fallback_card.x, fallback_card.y, fallback_card.width, fallback_card.height))
            selected += 1
            task.sleep(0.3)

    return selected


def calculate_dominant_hue(task: TriggerTask, region):
    """计算区域的主导色相，返回色相值(0-179)，无有效色相返回-1。"""
    box = task.box_of_screen(*region)
    frame = task.frame[box.y:box.y + box.height, box.x:box.x + box.width, :3]
    hue, sat, val = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))

    valid_hue = hue[(sat > 30) & (val > 30)]
    if len(valid_hue) == 0:
        return -1

    hist = cv2.calcHist([valid_hue.astype(np.float32)], [0], None, [180], [0, 180])
    return int(np.argmax(hist))


def is_button_active(task: TriggerTask, button_box):
    """判断按钮是否处于可点击状态（激活状态）。

    参数:
        task: TriggerTask实例
        button_box: 按钮文本的Box对象（像素坐标）

    返回:
        bool: True表示按钮可点击（激活），False表示不可点击（未激活/灰色）
    """
    # 计算左侧检测区域（按钮图标/背景区域）
    # 根据用户提供的例子推算比例：
    # 按钮box: (0.898, 0.908, 0.941, 0.950) w=0.043, h=0.042
    # 左侧区域: (0.866, 0.912, 0.895, 0.947) w=0.029, h=0.035
    # 左侧区域宽度 = 按钮宽度 * 0.67，x = 按钮x - 左侧区域宽度 * 1.1
    # 左侧区域高度 = 按钮高度 * 0.83，y = 按钮y + 按钮高度 * 0.1

    left_width = int(button_box.width * 0.67)
    left_height = int(button_box.height * 0.83)
    left_x = button_box.x - int(left_width * 1.1)
    left_y = button_box.y + int(button_box.height * 0.1)

    # 确保区域在屏幕内
    if left_x < 0:
        left_x = 0
    if left_y < 0:
        left_y = 0
    if left_x + left_width > task.width:
        left_width = task.width - left_x
    if left_y + left_height > task.height:
        left_height = task.height - left_y

    if left_width <= 0 or left_height <= 0:
        task.log_info(f"按钮左侧区域无效: ({left_x}, {left_y}, {left_width}, {left_height})")
        return False

    # 提取区域图像
    region_img = task.frame[left_y:left_y + left_height, left_x:left_x + left_width, :3]
    if region_img.size == 0:
        task.log_info("按钮左侧区域图像为空")
        return False

    # 计算平均BGR颜色
    avg_color = cv2.mean(region_img)[:3]  # B, G, R 平均值
    avg_b, avg_g, avg_r = avg_color

    # 判断是否接近禁用灰色 (195,195,195)
    # 容错范围：每个通道在190-200之间，且三个通道值接近
    # target_gray = 195
    tolerance = 5  # 允许±5的误差

    # 计算范围边界
    lower_bound = 120 #target_gray - tolerance  # 190
    upper_bound = 200 #target_gray + tolerance  # 200

    # 检查每个通道是否在目标范围内
    in_range = (
        lower_bound <= avg_b <= upper_bound and
        lower_bound <= avg_g <= upper_bound and
        lower_bound <= avg_r <= upper_bound
    )

    # 检查三个通道是否接近（最大差异小）
    max_diff = max(abs(avg_b - avg_g), abs(avg_g - avg_r), abs(avg_r - avg_b))
    is_close = max_diff < tolerance

    # 如果是接近(195,195,195)的灰色，按钮不可点击
    is_disabled_gray = in_range and is_close

    task.log_info(f"按钮左侧区域颜色: B={avg_b:.1f}, G={avg_g:.1f}, R={avg_r:.1f}, "
                  f"是否禁用灰色={is_disabled_gray} (范围{lower_bound}-{upper_bound}, 最大差异={max_diff:.1f})")

    # 如果是禁用灰色，按钮不可点击；否则可点击
    return not is_disabled_gray


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


# def group_dialog_columns(task: TriggerTask, region, max_width_ratio=0.25, align_tolerance=0.04):
#     """把区域内文本框按左边缘聚成对话框列。"""
#     x1, y1, x2, y2 = region
#     boxes = [
#         box for box in task.all_texts
#         if x1 <= (box.x + box.width / 2) / task.width <= x2
#         and y1 <= (box.y + box.height / 2) / task.height <= y2
#         and box.width / task.width <= max_width_ratio
#         and len(box.name) > 2
#     ]
#     columns = []
#     for box in sorted(boxes, key=lambda item: item.x):
#         left = box.x / task.width
#         center_x = (box.x + box.width / 2) / task.width
#         if columns and left - columns[-1]["left"] <= align_tolerance:
#             columns[-1]["centers"].append(center_x)
#             columns[-1]["texts"].append(box.name)
#         else:
#             columns.append({"left": left, "centers": [center_x], "texts": [box.name]})
#     return [
#         {"x": sum(column["centers"]) / len(column["centers"]), "texts": column["texts"]}
#         for column in columns
#     ]


# ------------------------- 帧卡住检测 -------------------------

def is_frame_stuck(task: TriggerTask, stuck_threshold_seconds=30, change_threshold=0.005):
    """
    基于像素变化检测画面是否卡住。
    在 task 上缓存 _prev_frame_gray 和 _last_change_time。
    连续 stuck_threshold_seconds 秒变化比例低于 change_threshold 返回 True。
    stuck_threshold_seconds: 判定卡住的连续秒数阈值，默认30秒
    change_threshold: 两帧之间变化像素比例阈值，默认0.005（0.5%）
    """
    if not hasattr(task, '_last_change_time'):
        task._last_change_time = time.time()
        task._prev_frame_gray = None

    frame = task.frame
    if frame is None:
        return False

    # 缩放灰度图以减少计算量
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (w // 4, h // 4))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    if task._prev_frame_gray is not None and gray.shape == task._prev_frame_gray.shape:
        diff = cv2.absdiff(gray, task._prev_frame_gray)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        change_ratio = cv2.countNonZero(thresh) / (gray.shape[0] * gray.shape[1])

        if change_ratio >= change_threshold:
            task._last_change_time = time.time()

    task._prev_frame_gray = gray

    return time.time() - task._last_change_time >= stuck_threshold_seconds


def handle_stuck_log(task: TriggerTask):
    """检测画面是否有变化，卡住则输出日志，不阻断其他处理。"""
    if is_frame_stuck(task):
        stuck_seconds = int(time.time() - task._last_change_time)
        task.log_info(f"画面卡住，已持续{stuck_seconds}秒")
    return False


# ------------------------- 页面处理函数（通用） -------------------------
# 约定: 每个函数处理一种页面, 处理成功返回 True, 未命中返回 False。

def handle_auto_stop(task: TriggerTask):
    """自动停止功能: 如果配置"几轮后停止(0为不停止)"不为0，
    且 node_status 中的 total_rounds 达到配置轮数，则自动 disable 当前任务。"""
    stop_rounds = _get_config_value(task, '几轮后停止(0为不停止)', 0)
    if stop_rounds and stop_rounds != 0:
        ns = getattr(task, 'node_status', None)
        if ns and ns.get('total_rounds', 0) >= stop_rounds:
            task.log_info(f"已达到配置的停止轮数 {stop_rounds}，当前 total_rounds={ns['total_rounds']}，自动停止任务")
            task.disable()
            return True
    return False


def log_credit(task: TriggerTask):
    """记录当前信用点数量（仅记录, 不拦截后续处理）。"""
    credit = _get_current_credit(task)
    if credit > 0:
        task.info_set("当前信用点", f"{credit}")
    return False


# def handle_stage_clear(task: TriggerTask):
#     """成功通关页面: 检测(0.142,0.806)处文本是否包含'战斗结束'，成功次数+1。"""
#     box = find_box_at_point(task, 0.142, 0.806)
#     if box and "战斗结束" in box.name:
#         task.log_info("检测到成功通关页面，success_rounds + 1")
#         if hasattr(task, 'node_status'):
#             task.node_status['success_rounds'] += 1
#     return False


def log_node_status(task: TriggerTask):
    """记录当前胜率（仅记录, 不拦截后续处理）。"""
    ns = getattr(task, 'node_status', None)
    if ns:
        total = ns.get('total_rounds', 0)
        node_count = ns.get('node_count', 0)
        node_type = ns.get('node_type', "")
        task.info_set("所处层数，节点，类型", f"第{ns['pass_final_boss_count']+1}层，第{node_count}节点，{node_type}")
        task.info_set("是否到达关底boss", f"{ns['reach_final_boss']}")
        task.info_set("是否进入关底boss战斗", f"{ns['final_boss_battle']}")
        task.info_set("是否已逃脱", f"{ns['is_escaped']}")
        equipment = _equipment_state(task)
        equipment_names = [
            _current_equipment_for_slot(task, equipment, slot)[0]
            for slot in range(3)
        ]
        task.info_set(
            "装备信息",
            "，".join(
                f"{slot + 1}号位：{name or '空'}"
                for slot, name in enumerate(equipment_names)
            ),
        )
        if total > 0:
            task.info_set("当前胜率", f"{ns['success_rounds']}/{total} ({ns['success_rounds']*100//total}%)")
        else:
            task.info_set("当前胜率",f"{ns['success_rounds']}/{total} NaN")
        task.log_info("")
    return False


def handle_battle_crash(task: TriggerTask):
    """战斗信息错乱 / 点击重试: 点击屏幕中央恢复。"""
    if find_text(task, r'出现错乱') or find_text(task, r'点击重试'):
        task.log_info("战斗信息出现错乱，点击恢复")
        task.click(0.5, 0.5)
        return True
    return False


def handle_close_page(task: TriggerTask):
    """提示"点击屏幕事件": 点击屏幕。"""
    box = find_text(task, _get_game_text(task, '点击屏幕'))
    if box:
        task.log_info("点击屏幕事件，点击屏幕")
        task.click_box(box)
        return True
    return False


def handle_refine_equipment_credit(task: TriggerTask):
    """提炼装备信用点页面：点击“以信用点接收”。"""
    box = find_box_at_point(task, 0.598, 0.635)
    if box and "以信用点接收" in box.name:
        task.log_info("检测到提炼装备信用点页面，点击以信用点接收")
        task.click_box(box)
        task.sleep(0.5)
        return True
    return False


def handle_center_confirm(task: TriggerTask):
    """页面中央的"确认"按钮。"""
    box = find_box_at_point(task, 0.667, 0.632)
    if box and _clean_match(box.name, "确认"):
        task.click(0.667, 0.632)
        task.sleep(1)
        return True
    return False


def handle_settlement(task: TriggerTask):
    """"结算"按钮。"""
    box = find_box_at_point(task, 0.941, 0.917)
    if box and _clean_match(box.name, "结算"):
        task.click(0.941, 0.917)
        if hasattr(task, 'node_status') and task.node_status.get('reach_final_boss', False):
            task.node_status['pass_final_boss_count'] += 1
            passed = task.node_status['pass_final_boss_count']
            task.log_info(f"检测到boss结算页面且 reach_final_boss=True，通关层数+1 (当前: {passed})")
            reset_layer_status(task)
        task.sleep(1)
        return True
    return False


def handle_skip(task: TriggerTask):
    """"跳过"按钮。"""
    box = find_box_at_point(task, 0.941, 0.917)
    if box and _clean_match(box.name, "跳过"):
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_destiny_choice(task: TriggerTask):
    """命运选择奖励页面: 随机选择一个命运标题。"""
    box = find_box_at_point(task, 0.499, 0.932)
    if box and _get_game_text(task, '请选择你的命运') in box.name:
        task.log_info("检测到命运选择奖励，进行相应操作")
        task.sleep(2)  # 给按钮一些加载时间

        # # 检查确认按钮是否已处于激活状态
        # # 在确认按钮点击位置附近查找"确认"文本
        # confirm_box = find_box_at_point(task, 0.884, 0.931)
        # if confirm_box and confirm_box.name == "确认":
        #     if is_button_active(task, confirm_box):
        #         task.log_info("确认按钮已激活，跳过选择（由其他逻辑处理确认）")
        #         return False  # 按钮已激活，不处理，让其他逻辑点击确认
        # 在命运标题区域随机选择一个
        titles = [
            b for b in task.all_texts
            if 0.202 <= (b.x + b.width / 2) / task.width <= 0.800
            and 0.474 <= (b.y + b.height / 2) / task.height <= 0.600
            and len(b.name.strip()) > 1
            and b.name not in ["确认", "返回", "跳过"]
        ]
        if titles:
            chosen = random.choice(titles)
            task.log_info(f"随机选择命运: {chosen.name}")
            task.click_box(chosen)
            task.sleep(1)
            # 选择命运后不点击确认按钮，返回False让其他逻辑处理
            return True
    return False


def handle_main_member_flash(task: TriggerTask):
    """主战员闪光选择页面: 依次选择三个并各自确认。"""
    box = find_box_at_point(task, 0.495, 0.936)
    if box and re.search(r'请选择获得', box.name):
        task.log_info("检测主战员闪光选择，进行相应操作")
        x, y = random.choice([(0.244, 0.446), (0.5, 0.446), (0.748, 0.485)])
        task.click(x, y)
        task.sleep(1)
        # task.click(0.884, 0.931)
        # task.sleep(1)
        return True  # 选择后不点击确认按钮，返回True让其他逻辑处理
    return False


def handle_card_reward(task: TriggerTask):
    """卡牌奖励页面: 在区域内OCR识别卡牌名，按优先级选择卡牌并确认。"""
    box = find_box_at_point(task, 0.498, 0.129)
    if not (box and _get_game_text(task, '卡牌奖励') in box.name):
        return False

    task.log_info("检测到卡牌奖励页面")
    target_boxes, target_click_positions = find_target_card(task)
    if target_boxes:
        click_position = target_click_positions[0]
        task.log_info(
            f"卡牌奖励页面: 检测到target卡牌，点击位置{click_position}"
        )
        task.click(*click_position)
        return True

    priority = _get_card_reward_priority(task)

    # 在指定区域内查找所有满足卡牌特征的文本框
    x1, y1, x2, y2 = 0.094, 0.231, 0.973, 0.875
    cards = [
        b for b in task.all_texts
        if x1 <= (b.x + b.width / 2) / task.width <= x2
        and y1 <= (b.y + b.height / 2) / task.height <= y2
        and _card_has_type_below(task, b)
        and len(b.name.strip()) > 1
    ]
    task.log_info(f"卡牌奖励区域识别到{len(cards)}张卡牌: {[b.name for b in cards]}")

    initial_card_name = _get_config_value(task, "刷初始卡牌", "")
    initial_card_name = initial_card_name.strip() if isinstance(initial_card_name, str) else ""
    node_status = getattr(task, "node_status", {})
    is_initial_node = (
        node_status.get("pass_final_boss_count", 0) == 0
        and node_status.get("node_count", 0) == 0
    )
    if initial_card_name and is_initial_node:
        initial_card = next(
            (card for card in cards if initial_card_name in card.name.strip()),
            None,
        )
        if initial_card:
            task.log_info(
                f"刷初始卡牌命中「{initial_card_name}」，点击该卡牌"
            )
            task.click_box(initial_card)
            task.sleep(1)
            return True
        task.log_info(
            f"刷初始卡牌未找到「{initial_card_name}」，点击ESC重新开始"
        )
        task.click(0.960, 0.053)
        task.sleep(1)
        return True

    chosen_card = None
    for pri_name in priority:
        chosen_card = next((b for b in cards if pri_name and pri_name in b.name), None)
        if chosen_card:
            task.log_info(f"按优先级选择卡牌: {chosen_card.name}（配置: {pri_name}）")
            break

    if chosen_card is None and cards:
        # 检查"跳过非优先级卡牌"配置
        if _get_config_value(task, '跳过非优先级卡牌', True):
            task.log_info("未命中优先级卡牌，跳过非优先级卡牌")
            # 在区域(0.620,0.883,0.990,0.983)内查找包含"跳过"的box并点击
            skip_box = next((b for b in task.all_texts
                             if 0.620 <= (b.x + b.width / 2) / task.width <= 0.990
                             and 0.883 <= (b.y + b.height / 2) / task.height <= 0.983
                             and "跳过" in b.name), None)
            if skip_box:
                task.click_box(skip_box)
            else:
                task.log_info("未找到跳过按钮，点击固定位置")
                task.click(0.745, 0.933)
            task.sleep(0.5)
            return True
        chosen_card = random.choice(cards)
        task.log_info(f"未命中优先级，随机选择卡牌: {chosen_card.name}")

    if chosen_card:
        task.click_box(chosen_card)
        task.sleep(1)
        return True
    return False


_EQUIPMENT_TYPE_SLOTS = {"攻击力": 0, "防御力": 1, "生命值": 2}


def _equipment_slot(type_text):
    """根据装备类型文本返回 equipment 下标，无法识别时返回 None。"""
    return next((slot for equipment_type, slot in _EQUIPMENT_TYPE_SLOTS.items()
                 if equipment_type in type_text), None)


def _equipment_priority(task: TriggerTask, slot):
    """读取指定装备位的优先级配置。"""
    priority = _get_config_value(task, f"装备{slot + 1}号位优先级", [])
    return list(priority) if isinstance(priority, (list, tuple)) else []


def _match_equipment_name(ocr_name, priority):
    """用双向包含匹配装备名，返回配置中的标准名称及优先级下标。"""
    for index, config_name in enumerate(priority):
        if ocr_name in config_name or config_name in ocr_name:
            return config_name, index
    return None, None


def _equipment_rank(name, priority):
    """返回已记录装备的优先级下标，未命中配置时排在配置装备之后。"""
    _, rank = _match_equipment_name(name, priority)
    return rank if rank is not None else len(priority)


def _equipment_state(task: TriggerTask):
    """获取并修正第一主战员的装备状态字典。"""
    member_status = getattr(task, "member_status", None)
    if not isinstance(member_status, dict):
        member_status = _initial_member_status()
        task.member_status = member_status
    equipment = member_status.setdefault("equipment", {})
    if not isinstance(equipment, dict):
        equipment = {"names": ["", "", ""], "descriptions": ["", "", ""]}
        member_status["equipment"] = equipment
    elif "names" not in equipment or "descriptions" not in equipment:
        old_equipment = equipment
        equipment = {"names": ["", "", ""], "descriptions": ["", "", ""]}
        for equipment_name, description in old_equipment.items():
            for slot in range(3):
                if _match_equipment_name(
                    equipment_name,
                    _equipment_priority(task, slot),
                )[0]:
                    equipment["names"][slot] = equipment_name
                    equipment["descriptions"][slot] = description
                    break
        member_status["equipment"] = equipment
    for key in ("names", "descriptions"):
        values = equipment.get(key)
        if not isinstance(values, list):
            values = []
        equipment[key] = (values + ["", "", ""])[:3]
    if not isinstance(member_status.get("deck"), dict):
        member_status["deck"] = {}
    return equipment


def _member_deck_state(task: TriggerTask):
    """获取并修正第一主战员的卡组状态字典。"""
    member_status = getattr(task, "member_status", None)
    if not isinstance(member_status, dict):
        member_status = _initial_member_status()
        task.member_status = member_status
    deck = member_status.setdefault("deck", {})
    if not isinstance(deck, dict):
        deck = {}
        member_status["deck"] = deck
    return deck


def _current_equipment_for_slot(task: TriggerTask, equipment, slot):
    """按槽位读取当前装备名称及其优先级。"""
    priority = _equipment_priority(task, slot)
    names = equipment.get("names", [])
    equipment_name = names[slot] if slot < len(names) else ""
    if not equipment_name:
        return "", len(priority)
    return equipment_name, _equipment_rank(equipment_name, priority)


def _equipment_info(task: TriggerTask, name_point, type_point):
    """从指定坐标读取装备名称、槽位和配置中的标准名称。"""
    name_box = find_box_at_point(task, *name_point)
    type_box = find_box_at_point(task, *type_point)
    if not name_box or not type_box:
        return None
    slot = _equipment_slot(type_box.name)
    if slot is None:
        return None
    priority = _equipment_priority(task, slot)
    canonical_name, rank = _match_equipment_name(name_box.name, priority)
    return {
        "ocr_name": name_box.name,
        "name": canonical_name or name_box.name,
        "slot": slot,
        "priority": priority,
        "rank": rank,
    }


def handle_equipment(task: TriggerTask):
    """装备选择/安装界面: 按装备位优先级选择，并维护第一主战员的装备状态。"""
    title = find_box_at_point(task, 0.499, 0.126)
    if not (title and title.name == "装备"):
        return False

    task.log_info("检测到装备页面")
    equipment = _equipment_state(task)
    equip_hint = find_box_at_point(task, 0.921, 0.135)

    if equip_hint and _get_game_text(task, '请选择主战员') in equip_hint.name:
        task.log_info("检测到安装装备界面")
        new_equipment = _equipment_info(task, (0.245, 0.412), (0.217, 0.464))
        if not new_equipment:
            task.log_info("未能识别待安装装备的名称或类型")
            return False
        equipment_desc = _get_region_text(task, (0.179, 0.492, 0.542, 0.668))
        task.log_info(f"待安装装备描述: 「{equipment_desc}」")

        slot = new_equipment["slot"]
        current_name, current_rank = _current_equipment_for_slot(task, equipment, slot)
        new_rank = new_equipment["rank"]
        should_install_first = not current_name or (
            new_rank is not None and new_rank < current_rank
        )

        px1, py1 = int(0.609 * task.width), int(0.290 * task.height)
        px2, py2 = int(0.652 * task.width), int(0.789 * task.height)
        lv_texts = sorted(
            [b for b in task.all_texts
             if b.x >= px1 and b.y >= py1 and b.x + b.width <= px2 and b.y + b.height <= py2
             and "等级" in b.name],
            key=lambda b: b.y
        )

        if should_install_first and lv_texts:
            chosen = lv_texts[0]
            equipment["names"][slot] = new_equipment["name"]
            equipment["descriptions"][slot] = equipment_desc
            task.log_info(
                f"{slot + 1}号位装备「{new_equipment['name']}」优于当前装备「{current_name}」，安装给第一主战员"
            )
            task.click(0.756, (chosen.y + chosen.height / 2) / task.height)
            task.sleep(1)
            return False

        if len(lv_texts) > 1:
            chosen = random.choice(lv_texts[1:])
            task.log_info(
                f"{slot + 1}号位已有更高或相同优先级装备「{current_name}」，随机安装给其他主战员"
            )
            task.click(0.756, (chosen.y + chosen.height / 2) / task.height)
            task.sleep(1)
            return False

        refine_box = next(
            (b for b in task.all_texts
             if 0.522 <= (b.x + b.width / 2) / task.width <= 0.999
             and 0.879 <= (b.y + b.height / 2) / task.height <= 0.996
             and "提炼" in b.name),
            None
        )
        if refine_box:
            task.log_info(f"{slot + 1}号位无需替换且没有其他主战员可选，点击提炼")
            task.click_box(refine_box)
            task.sleep(1)
            return True

        task.log_info("未找到可选择的主战员或提炼按钮")
        return False

    candidates = []
    candidate_specs = [
        ((0.452, 0.246), (0.412, 0.297), (0.518, 0.454)),
        ((0.448, 0.578), (0.412, 0.633), (0.521, 0.600)),
    ]
    for name_point, type_point, click_position in candidate_specs:
        candidate = _equipment_info(task, name_point, type_point)
        if candidate:
            candidate["click_position"] = click_position
            candidates.append(candidate)
    task.log_info(
        f"检测到选择装备界面，候选装备: "
        f"{[(candidate['ocr_name'], candidate['slot'] + 1) for candidate in candidates]}"
    )

    chosen_index = None
    for slot in range(3):
        current_name, current_rank = _current_equipment_for_slot(task, equipment, slot)
        for index, candidate in enumerate(candidates):
            if candidate["slot"] != slot or candidate["rank"] is None:
                continue
            if not current_name or candidate["rank"] < current_rank:
                chosen_index = index
                task.log_info(
                    f"优先选择{slot + 1}号位装备「{candidate['name']}」，当前装备「{current_name}」"
                )
                break
        if chosen_index is not None:
            break

    if chosen_index is None:
        empty_slot_candidates = [
            candidate for candidate in candidates
            if not _current_equipment_for_slot(task, equipment, candidate["slot"])[0]
        ]
        if empty_slot_candidates:
            chosen_candidate = random.choice(empty_slot_candidates)
            click_position = chosen_candidate["click_position"]
            task.log_info(
                f"候选装备均未命中升级条件，优先选择空缺的"
                f"{chosen_candidate['slot'] + 1}号位装备「{chosen_candidate['ocr_name']}」"
            )
        else:
            task.log_info("候选装备均未命中升级条件且对应位置均非空，随机选择一个装备")
            click_position = random.choice([spec[2] for spec in candidate_specs])
    else:
        click_position = candidates[chosen_index]["click_position"]
    task.click(*click_position)
    task.sleep(1)
    return False


# 卡牌操作关键词 → 配置 key 映射
_SELECT_CARD_CONFIG_KEYS = {
    "移除": "移除卡牌列表",
    "复制": "复制卡牌列表",
    "闪光": "闪光卡牌列表",
    "灵光一闪": "闪光卡牌列表",
}


def handle_select_card(task: TriggerTask):
    """统一卡牌选择页面: 在(0.198,0.039)处检测文本，按移除/复制/闪光等关键字匹配配置并选择卡牌。"""
    box = find_box_at_point(task, 0.198, 0.039)
    if not box:
        return False
    m = re.search(r'请选择(\d*)张*.*?(移除|复制|闪光|灵光一闪).*?卡牌', box.name)
    if not m:
        return False
    count_text = m.group(1)
    action = m.group(2)
    count = int(count_text) if count_text else 1
    config_key = _SELECT_CARD_CONFIG_KEYS.get(action)
    if config_key is None:
        return False
    task.log_info(f"检测到卡牌{action}选择，需选择{count}张，配置key={config_key}")

    # 日志打印右下角选牌操作提示
    action_tip = find_box_at_point(task, 0.945, 0.918)
    if action_tip:
        task.log_info(f"右下角选牌操作提示: 「{action_tip.name}」")

    select_card(task, _get_card_list(task, config_key), fallback_delete=True, count=count, action=action)
    return True


def handle_copy_card_choice(task: TriggerTask):
    """复制卡牌选择页面: 动态识别最多三张卡牌，按复制卡牌列表优先级选择。"""
    box = find_box_at_point(task, 0.498, 0.133)
    if not (box and "请选择要复制的卡牌" in box.name):
        return False

    task.log_info("检测到复制卡牌选择页面")
    target_boxes, target_click_positions = find_target_card(task)
    if target_boxes:
        click_position = target_click_positions[0]
        task.log_info(
            f"复制卡牌选择: 检测到target卡牌，点击位置{click_position}"
        )
        task.click(*click_position)
        return True

    name_boxes = []
    for text_box in task.all_texts:
        center_x = (text_box.x + text_box.width / 2) / task.width
        center_y = (text_box.y + text_box.height / 2) / task.height
        name = text_box.name.strip()
        if not (
            0.080 <= center_x <= 0.948
            and 0.183 <= center_y <= 0.367
            and name
            and _card_has_type_below(task, text_box)
        ):
            continue
        if len(name) == 1 and (
            name.isdigit()
            or re.fullmatch(r"[A-Za-z]", name)
            or not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", name)
        ):
            continue
        name_boxes.append(text_box)

    if len(name_boxes) > 3:
        task.log_info(
            f"识别到{len(name_boxes)}个候选卡牌名，保留文本长度最长的三个"
        )
        name_boxes = sorted(
            name_boxes,
            key=lambda candidate: len(candidate.name.strip()),
            reverse=True,
        )[:3]
    name_boxes.sort(key=lambda candidate: candidate.x)

    cards = []
    for index, name_box in enumerate(name_boxes):
        name_center_x = (name_box.x + name_box.width / 2) / task.width
        name_bottom_y = (name_box.y + name_box.height) / task.height
        desc_region = (
            max(0.0, name_center_x - 0.0841),
            max(0.0, name_bottom_y + 0.0883),
            min(1.0, name_center_x + 0.1129),
            min(1.0, name_bottom_y + 0.5063),
        )
        name = name_box.name.strip()
        desc = _get_region_text(task, desc_region)
        cards.append({"name": name, "box": name_box, "desc": desc})
        task.log_info(
            f"复制卡牌 卡牌{index + 1}: 名称=「{name}」 描述=「{desc}」"
        )

    priority = _get_config_value(task, '复制卡牌列表', [])
    for pri_name in priority:
        for card in cards:
            if card["name"] and pri_name in card["name"]:
                task.log_info(f"复制卡牌选择: 按优先级选择「{card['name']}」(匹配「{pri_name}」)")
                task.click_box(card["box"])
                task.sleep(0.5)
                return True

    task.log_info("复制卡牌选择: 未命中任何优先级，return False")
    return False


def handle_copy_member(task: TriggerTask):
    """选择要复制卡牌的主战员页面。"""
    box = find_box_at_point(task, 0.502, 0.932)
    if not (box and "选择要复制卡牌的主战员" in box.name):
        return False

    task.log_info("检测到卡牌复制主战员选择事件，进行相应操作")

    confirm_box = task.box_of_screen(0.145, 0.044, 0.856, 0.214)
    click_positions = [(0.228, 0.510), (0.504, 0.504), (0.755, 0.508)]

    for i, (cx, cy) in enumerate(click_positions):
        task.log_info(f"点击位置({cx}, {cy})")
        task.click(cx, cy)
        task.sleep(0.5)

        feature = task.wait_feature("copymemberconfirm", box=confirm_box, time_out=2)
        if feature:
            task.log_info(f"点击位置({cx}, {cy})后成功找到copymemberconfirm")
            return True
        else:
            task.log_info(f"点击位置({cx}, {cy})后未找到copymemberconfirm，继续尝试")

    task.log_info("所有尝试均未找到copymemberconfirm")
    return True


def handle_convert_card(task: TriggerTask):
    """转换卡牌页面: 跳过转换。"""
    box = find_box_at_point(task, 0.226, 0.046)
    if box and _get_game_text(task, '转换的卡牌') in box.name:
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
    box = find_exact_text(task, _get_game_text(task, '继续'))
    if box:
        task.log_info("检测到下一步操作，点击继续")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_confirm(task: TriggerTask):
    """通用"确认"按钮。"""
    box = find_exact_text(task, "确认")
    if box:
        if is_button_active(task, box):
            task.log_info("检测到确认操作，点击确认")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("确认按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_convert(task: TriggerTask):
    """通用"转换"按钮: 按钮激活则点击转换，未激活则点击跳过(0.776,0.926)。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "转换"):
        if is_button_active(task, box):
            task.log_info("检测到转换按钮，点击转换")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("转换按钮未激活（灰色），点击跳过")
            task.click(0.776, 0.926)
            task.sleep(1)
            return True
    return False

def handle_remove(task: TriggerTask):
    """通用"移除"按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "移除"):
        if is_button_active(task, box):
            task.log_info("检测到移除操作，点击移除")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("移除按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_flash(task: TriggerTask):
    """通用"闪光"按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _get_game_text(task, '闪光') in box.name:
        if is_button_active(task, box):
            task.log_info("检测到闪光操作，点击闪光")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("闪光按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_reflash(task: TriggerTask):
    """通用"重新闪光"按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _get_game_text(task, '重新闪光') in box.name:
        if is_button_active(task, box):
            task.log_info("检测到重新闪光操作，点击重新闪光")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("重新闪光按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_grant_flash(task: TriggerTask):
    """通用"赋予闪光"按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "赋予闪光"):
        if is_button_active(task, box):
            task.log_info("检测到赋予闪光操作，点击赋予闪光")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("赋予闪光按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_copy(task: TriggerTask):
    """通用"复制"按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "复制"):
        if is_button_active(task, box):
            task.log_info("检测到复制操作，点击复制")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("复制按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_enter(task: TriggerTask):
    """通用"进入"按钮。"""
    box = find_exact_text(task, "进入")
    if box:
        task.log_info("检测到进入按钮，点击进入")
        task.click_box(box)
        reset_mission_status(task)
        task.sleep(1)
        return True
    return False

def handle_equipment_recast(task: TriggerTask):
    """装备重铸页面: 点击确认重铸。"""
    box = find_box_at_point(task, 0.501, 0.128)
    if box and _get_game_text(task, '装备重铸') in box.name:
        task.log_info("检测到装备重铸页面，点击跳过")
        task.click(0.749, 0.932)
        task.sleep(1)
        return True
    return False


def handle_event_task(task: TriggerTask):
    """事件任务页面: 识别标题+描述区域，按任务优先级匹配描述选择推进。"""
    rewards = task.find_feature(feature_name="taskreward")
    if rewards:
        reward = rewards[0]
        cx = (reward.x + reward.width / 2) / task.width
        cy = (reward.y + reward.height / 2) / task.height
        if 0.437 <= cx <= 0.902 and 0.350 <= cy <= 0.614:
            task.log_info("检测到任务奖励图标，优先点击")
            task.click_box(reward)
            return True

    bottom_box = find_box_at_point(task, 0.516, 0.971)
    if bottom_box and re.search(r'\d+/\d+', bottom_box.name):
        return False

    task_open_box = task.box_of_screen(0.116, 0.899, 0.888, 0.994)
    task_open_boxes = task.find_feature(feature_name="taskopen", box=task_open_box)
    if task_open_boxes:
        task.log_info("检测到taskopen特征，点击打开任务")
        task.click_box(task_open_boxes[0])
        task.sleep(1)
        return True

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
        return False

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
        return False

    tasks_info = []
    for title in titles:
        desc_left = title.x
        desc_top = title.y + title.height
        desc_right = title.x + 0.221 * task.width
        desc_bottom = title.y + title.height + 0.121 * task.height

        desc_lines = [
            b for b in task.all_texts
            if b.x >= desc_left - 0.01 * task.width and b.y + b.height >= desc_top - 0.02 * task.height
            and b.x + b.width <= desc_right + 0.01 * task.width and b.y <= desc_bottom + 0.02 * task.height
            and b.name not in ["确认", "返回", "跳过"]
        ]

        if not desc_lines:
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

    initial_card_name = _get_config_value(task, "刷初始卡牌", "")
    initial_card_name = initial_card_name.strip() if isinstance(initial_card_name, str) else ""
    node_status = getattr(task, "node_status", {})
    is_initial_node = (
        node_status.get("pass_final_boss_count", 0) == 0
        and node_status.get("node_count", 0) == 0
    )
    if initial_card_name and is_initial_node:
        legend_card_task = next(
            (
                task_info
                for task_info in tasks_info
                if "传说卡牌" in task_info["description"]
            ),
            None,
        )
        if legend_card_task:
            task.log_info(
                f"刷初始卡牌「{initial_card_name}」：选择包含“传说卡牌”的事件任务"
            )
            chosen_x = legend_card_task["x"]
            task.click(chosen_x, 0.832)
            task.sleep(1)
            task.click(chosen_x, 0.952)
            task.sleep(1)
            return True
        task.log_info(
            f"刷初始卡牌「{initial_card_name}」：未找到包含“传说卡牌”的事件任务，点击ESC重新开始"
        )
        task.click(0.959, 0.053)
        task.sleep(1)
        return True

    # 检查任务区域中是否有 treasure 特征
    treasure_box = task.box_of_screen(0.477, 0.336, 0.841, 0.540)
    treasure_features = task.find_feature(feature_name="treasure", box=treasure_box)
    if treasure_features:
        task.log_info("检测到事件任务区域中有treasure特征，优先点击")
        task.click_box(treasure_features[0])
        task.sleep(2)
        return True

    # 读取拉黑任务列表
    blacklist = _get_config_value(task, '拉黑任务', ["咒术卡牌"])
    blacklist = list(blacklist) if isinstance(blacklist, (list, tuple)) else []
    if blacklist:
        # 过滤掉描述包含拉黑关键词的任务
        filtered_tasks = [
            t for t in tasks_info
            if not any(is_subsequence(bk, t['description']) for bk in blacklist)
        ]
        if len(filtered_tasks) < len(tasks_info):
            task.log_info(f"拉黑任务关键词: {blacklist}，过滤前{len(tasks_info)}个，过滤后{len(filtered_tasks)}个")
            for t in tasks_info:
                if t not in filtered_tasks:
                    task.log_info(f"  已拉黑: {t['title']} | 描述: {t['description']}")
        # 如果全部被拉黑，兜底用原列表
        if not filtered_tasks:
            task.log_info("所有任务均被拉黑，兜底使用原列表")
            filtered_tasks = tasks_info
        tasks_info = filtered_tasks

    priority = _get_config_value(task, '任务优先级', [])
    chosen = None
    for keyword in priority:
        for t in tasks_info:
            if is_subsequence(keyword, t['description']):
                chosen = t
                task.log_info(f"优先选择「{keyword}」-> 标题: {t['title']}, 描述: {t['description']}")
                break
        if chosen is not None:
            break

    if chosen is None:
        chosen = random.choice(tasks_info)
        task.log_info(f"未命中优先级描述, 从{len(tasks_info)}个可选任务中随机选择: {chosen['title']}")

    chosen_x = chosen['x']
    task.click(chosen_x, 0.832)
    task.sleep(1)
    task.click(chosen_x, 0.952)
    task.sleep(1)
    return True


def handle_route_selection(task: TriggerTask):
    """路线选择页面: 识别节点类型，按优先级排序后依次点击所有节点，每次间隔1秒。
    同时负责节点计数：离开路线页面时 node_count +1。"""
    position_box = task.box_of_screen(0.335, 0.568, 0.453, 0.751)
    position_feature = task.find_feature(feature_name="position", box=position_box)
    cant_receive = find_box_at_point(task, 0.186, 0.850)
    is_route_page = position_feature or (cant_receive and "无法接收到梦境号" in cant_receive.name)

    # 如果当前页面不是路线选择页面，但 enter_new_node 为 True（刚离开路线页面），计数+1
    if not is_route_page:
        if hasattr(task, 'node_status') and task.node_status.get('enter_new_node', False):
            task.node_status['enter_new_node'] = False
            task.node_status['node_count'] += 1
            task.log_info(f"离开路线选择页面，当前节点计数: {task.node_status['node_count']}")
        return False

    # 是路线选择页面，标记进入新节点
    if hasattr(task, 'node_status'):
        task.node_status['enter_new_node'] = True

    task.log_info("检测到路线选择页面，按优先级依次点击节点")

    # 更新节点状态：进入路线选择页面时 flash_or_rest 置为 True
    if hasattr(task, 'node_status'):
        task.node_status['flash_or_rest'] = True
        task.log_info("检测到路线选择页面，更新 node_status['flash_or_rest']=True")
        # 检查"进入商店"配置，若为 True 则同时更新 shop 状态
        if _get_config_value(task, '进入商店', False):
            task.node_status['shop'] = True
            task.log_info(f"进入商店配置为True，更新 node_status['shop']=True")
    task.sleep(1)

    route_box = task.box_of_screen(0.656, 0.053, 0.977, 0.908)
    node_feature_types = {
        "safezone": "休息",
        "enemy": "小怪",
        "elite": "精英",
        "event": "事件",
        "settlement": "结算",
    }
    nodes = []
    for feature_name, node_type in node_feature_types.items():
        for feature_box in task.find_feature(feature_name=feature_name, box=route_box):
            nodes.append({
                "feature_name": feature_name,
                "node_type": node_type,
                "box": feature_box,
                "special_features": [],
            })

    # 找不到任何普通节点类型特征时，当前路线节点即为boss。
    if not nodes:
        task.log_info("检测到最终boss节点，点击进入")
        if hasattr(task, 'node_status'):
            task.node_status['reach_final_boss'] = True
            task.node_status['node_type'] = "boss"

        # 检查"第几层boss前自动暂停"配置
        pause_config = _get_config_value(task, '第几层boss前自动暂停', "不暂停")
        if pause_config != "不暂停":
            try:
                pause_layer = int(pause_config)
                current_layer = task.node_status.get('pass_final_boss_count', 0)
                if pause_layer - 1 == current_layer:
                    task.log_info(f"配置在第{pause_layer}层boss前暂停（当前已通过{current_layer}层），暂停工具")
                    from ok import og
                    og.executor.pause()
                    task.sleep(5)
                    return True
            except (ValueError, TypeError):
                pass

        task.click(0.815, 0.492)
        task.sleep(2)
        return True

    def relative_center(box):
        return (
            (box.x + box.width / 2) / task.width,
            (box.y + box.height / 2) / task.height,
        )

    # 特殊特征优先级：负数高于普通节点，正数低于普通节点。
    special_feature_priorities = {
        "shop": -1,
        "kalei": -1,
        "hard": 1,
    }

    # 每个特殊特征只归属到距离最近的一个节点类型特征。
    for special_name in special_feature_priorities:
        for special_box in task.find_feature(feature_name=special_name, box=route_box):
            special_x, special_y = relative_center(special_box)
            nearest_node = min(
                nodes,
                key=lambda node: (
                    (relative_center(node["box"])[0] - special_x) ** 2
                    + (relative_center(node["box"])[1] - special_y) ** 2
                ),
            )
            nearest_node["special_features"].append(special_name)
            task.log_info(
                f"特殊特征「{special_name}」分配给"
                f"「{nearest_node['node_type']}」节点"
            )

    priority = _get_route_priority(task)
    task.log_info(f"路线优先级配置: {priority}")
    task.log_info(
        f"识别到的路线节点: "
        f"{[(node['node_type'], node['special_features']) for node in nodes]}"
    )

    priority_index = {node_type: index for index, node_type in enumerate(priority)}

    def sort_key(node):
        if node["node_type"] == "结算":
            type_priority = len(priority) + 1
        else:
            type_priority = priority_index.get(node["node_type"], len(priority))
        special_priority = min(
            (special_feature_priorities[name] for name in node["special_features"]),
            default=0,
        )
        center_x, center_y = relative_center(node["box"])
        return type_priority, special_priority, center_y, center_x

    sorted_nodes = sorted(nodes, key=sort_key)
    node = sorted_nodes[0]

    # 更新 node_type 为最优先的节点类型
    if hasattr(task, 'node_status'):
        task.node_status['node_type'] = node["node_type"]
        task.log_info(f"更新 node_type 为「{node['node_type']}」")

    center_x, center_y = relative_center(node["box"])
    click_x = center_x - 0.095
    click_y = center_y - 0.0065
    task.log_info(
        f"点击{node['node_type']}节点"
        f"（特殊特征: {node['special_features']}，位置: {click_x:.3f}, {click_y:.3f}）"
    )
    task.click(click_x, click_y)

    task.sleep(2)

    return True


def handle_obtain_reward(task: TriggerTask):
    """获得奖励页面: 点击领取。若此时 reach_final_boss 为 True，说明已通关关底boss，过层+1并重置层状态。"""
    box = find_box_at_point(task, 0.924, 0.922)
    if box and _clean_match(box.name, "获得"):
        task.log_info("检测到获得奖励页面，点击领取")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_leave(task: TriggerTask):
    """离开按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "离开"):
        if is_button_active(task, box):
            task.log_info("检测到离开按钮，点击离开")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("离开按钮未激活（灰色），跳过点击")
            return False
    return False
def handle_next_step(task: TriggerTask):
    """通用"下一步"按钮: 在区域(0.833,0.885,0.954,0.957)内检测文本，编辑距离<=2即匹配。"""
    x1, y1, x2, y2 = 0.833, 0.885, 0.954, 0.957
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            if _edit_distance(b.name, "下一步", max_dist=2):
                task.log_info(f"检测到下一步按钮「{b.name}」，点击")
                task.click_box(b)
                task.sleep(1)
                return True
    return False


def handle_craft(task: TriggerTask):
    """合成按钮。"""
    box = find_box_at_point(task, 0.938, 0.903)
    if box and _clean_match(box.name, "合成"):
        if is_button_active(task, box):
            task.log_info("检测到合成按钮，点击合成")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("合成按钮未激活（灰色），跳过点击")
            return False
    return False

def handle_select(task: TriggerTask):
    """通用"选择"按钮。"""
    box = find_box_at_point(task, 0.945, 0.918)
    if box and _clean_match(box.name, "选择"):
        if is_button_active(task, box):
            task.log_info("检测到选择按钮，点击选择")
            task.click_box(box)
            task.sleep(1)
            return True
        else:
            task.log_info("选择按钮未激活（灰色），跳过点击")
            return False
    return False


def _find_rest_feature(task: TriggerTask):
    """在休息区域查找rest特征，命中时输出置信度。"""
    search_box = task.box_of_screen(0.157, 0.503, 0.467, 0.863)
    rest_feature = task.find_one(feature_name="rest", box=search_box)
    if rest_feature:
        task.log_info(f"检测到rest特征，匹配置信度: {rest_feature.confidence:.2%}")
    return rest_feature


def handle_rest(task: TriggerTask):
    """休息界面: 检测rest特征并根据flash_or_rest状态决定是否点击。"""
    rest_feature = _find_rest_feature(task)
    if rest_feature and hasattr(task, 'node_status') and task.node_status.get('flash_or_rest', False):
        task.log_info("检测到休息界面，点击休息")
        task.click_box(rest_feature)
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


def handle_shop(task: TriggerTask):
    """德朗商店: 若信用点足够则点击移除卡牌。"""
    box = find_box_at_point(task, 0.729, 0.261)
    soldout = find_box_at_point(task, 0.727, 0.286)
    if (box and "移除卡牌" in box.name) or (soldout and "售" in soldout.name):
        task.log_info("handle_shop: 通过页面判定（移除卡牌或售罄）")
        if soldout and "售" in soldout.name:
            task.log_info(f"德朗商店: 移除卡牌已售罄")
            return False
        current_credit = _get_current_credit(task)
        task.log_info(f"handle_shop: 当前信用点={current_credit}")
        if current_credit <= 0:
            task.log_info("handle_shop: 信用点读取失败，return False")
            return False

        cost_box = find_box_at_point(task, 0.724, 0.319)
        task.log_info(f"handle_shop: 0.724,0.319处费用文本='{cost_box.name if cost_box else None}'")
        if not (cost_box and cost_box.name.isdigit()):
            task.log_info("handle_shop: 费用读取失败，return False")
            return False
        cost = int(cost_box.name)
        if cost <= current_credit:
            task.log_info(f"德朗商店: 移除卡牌需{cost}信用点，当前{current_credit}，足够，点击移除")
            task.click_box(box)
            return True
        else:
            task.log_info(f"德朗商店: 移除卡牌需{cost}信用点，当前{current_credit}，不足，跳过")
            return False
    return False


def handle_view_original(task: TriggerTask):
    """卡牌闪光（查看原件）事件: 聚类卡牌名和效果描述，按 FLASH_PRIORITY 优先选择。"""
    box1 = find_box_at_point(task, 0.890, 0.051)
    box2 = find_box_at_point(task, 0.896, 0.131)
    if not ((box1 and (_get_game_text(task, '查看原件') in box1.name or _get_game_text(task, '查看之前的闪光') in box1.name)) or (box2 and (_get_game_text(task, '查看原件') in box2.name or _get_game_text(task, '查看之前的闪光') in box2.name))):
        return False

    target_boxes, target_click_positions = find_target_card(task)
    if target_boxes:
        click_position = target_click_positions[0]
        task.log_info(
            f"卡牌闪光事件: 检测到target卡牌，点击位置{click_position}"
        )
        task.click(*click_position)
        return True

    name_cols = _cluster_region_boxes(task, (0.148, 0.192, 0.859, 0.325))
    desc_cols = _cluster_region_boxes(task, (0.154, 0.456, 0.859, 0.786))

    if not name_cols or not desc_cols:
        return False

    cards = []
    for name_col in name_cols:
        nearest_desc = min(desc_cols, key=lambda d: abs(d['x'] - name_col['x']))
        card_name = name_col['texts'][0] if name_col['texts'] else ''
        cards.append({
            'x': (name_col['x'] + nearest_desc['x']) / 2,
            'name': card_name,
            'descs': nearest_desc['texts'],
        })

    log_parts = [f"检测到卡牌闪光事件，卡牌名称是{cards[0]['name']}"]
    for i, card in enumerate(cards, 1):
        log_parts.append(f"闪光{i}效果是{'、'.join(card['descs'])}")
    task.log_info('，'.join(log_parts))

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
                if any(is_subsequence(desc_keyword, d) for d in card['descs']):
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


def handle_escape(task: TriggerTask):
    """逃脱页面: 检测到逃脱按钮后点击逃脱。"""
    escape_box = find_box_at_point(task, 0.952, 0.928)
    if escape_box and _get_game_text(task, '逃脱') in escape_box.name:
        task.log_info("检测到逃脱页面，点击逃脱")
        task.click_box(escape_box)
        task.node_status["is_escaped"] = True
        task.sleep(0.5)
        return True
    return False


# def handle_battle_failed(task: TriggerTask):
#     """战斗失败页面: 记录失败并重置boss状态。"""
#     box = find_box_at_point(task, 0.291, 0.718)
#     if box and box.name == "战斗失败":
#         task.log_info("检测到战斗失败，记录失败并重置boss状态")
#         if hasattr(task, 'node_status'):
#             task.node_status['total_rounds'] += 1
#             task.log_info(f"战斗失败，total_rounds={task.node_status['total_rounds']}")
#             task.node_status['pass_final_boss_count'] = 0
#             task.node_status['reach_final_boss'] = False
#             task.node_status['final_boss_battle'] = False
#     return False

def handle_expedition_result(task: TriggerTask):
    """探险结果页面: 如果0.625,0.122处有"探险结果"，则为探险结果页面。
    如果0.928,0.122处有"完成"，则success_rounds+1。"""
    title_box = find_box_at_point(task, 0.625, 0.122)
    if not (title_box and "探险结果" in title_box.name):
        return False
    task.sleep(2)
    task.all_texts = _simplify_texts(task.ocr())
    title_box = find_box_at_point(task, 0.625, 0.122)
    if not (title_box and "探险结果" in title_box.name):
        return False

    task.log_info("检测到探险结果页面")
    complete_box = find_box_at_point(task, 0.928, 0.122)
    failed_box = find_box_at_point(task, 0.296, 0.719)
    if hasattr(task, 'node_status'):
        task.node_status['total_rounds'] += 1
    if complete_box and "完成" in complete_box.name:
        if hasattr(task, 'node_status'):
            task.node_status['success_rounds'] += 1
            task.log_info("出击模式探险结果: 成功")
    elif complete_box and "失败" in complete_box.name:
        if not _get_config_value(task, '只打第一层', False):
            task.log_info("出击模式探险结果: 失败")
        elif task.node_status.get('pass_final_boss_count', 0) == 0:
            task.log_info("出击模式探险结果: 失败")
    elif not complete_box and not failed_box:
        if _get_config_value(task, '只打第一层', False) and task.node_status.get('pass_final_boss_count', 0) >= 1: # 完成第一层任务
            task.log_info("卡厄思模式探险结果: 成功")
        elif not _get_config_value(task, '只打第一层', False) and not task.node_status.get('is_escaped', 0): # 完成了任务且没有逃脱
            task.node_status['success_rounds'] += 1
            task.log_info("卡厄思模式探险结果: 成功")
        else:
            task.log_info("卡厄思模式探险结果: 失败")
    else:
        task.log_info("卡厄思模式探险结果: 失败")
    task.log_info(f"探险完成，成功次数/总次数={task.node_status['success_rounds']}/{task.node_status['total_rounds']}")
    if hasattr(task, 'node_status'):
        reset_mission_status(task)
    return False


def _initial_node_status():
    """返回 node_status 的初始副本。"""
    return {"shop": False, "flash_or_rest": False, "reach_final_boss": False, "final_boss_battle": False,
            "pass_final_boss_count": 0, "total_rounds": 0, "success_rounds": 0,
            "node_count": 0, "enter_new_node": False, "node_type": "", "is_escaped": False}


def _initial_member_status():
    """返回第一主战员状态的初始副本。"""
    return {
        "equipment": {
            "names": ["", "", ""],
            "descriptions": ["", "", ""],
        },
        "deck": {},
    }


def _finish_only_first_layer(task: TriggerTask) -> bool:
    """检查并完成只打第一层的退出操作：如果 pass_final_boss_count >= 1 且配置'只打第一层'为 True，则成功次数+1、点击退出并返回 True。"""
    if hasattr(task, 'node_status') and task.node_status.get('pass_final_boss_count', 0) >= 1 and _get_config_value(task, '只打第一层', False):
        task.node_status['success_rounds'] += 1
        task.log_info(f"只打第一层任务已完成，success_rounds + 1 (当前: {task.node_status['success_rounds']}), 退出结算页面")
        task.click(0.959, 0.051)
        task.sleep(1)
        return True
    return False


def reset_all_status(task: TriggerTask):
    """重置所有状态：恢复节点状态和第一主战员状态。"""
    if getattr(task, 'node_status', None) is not None:
        task.node_status = _initial_node_status()
    task.member_status = _initial_member_status()


def reset_mission_status(task: TriggerTask):
    """重置任务状态：保留任务统计，重置节点状态和第一主战员状态。"""
    ns = getattr(task, 'node_status', None)
    if ns is not None:
        keep = {'total_rounds': ns.get('total_rounds', 0), 'success_rounds': ns.get('success_rounds', 0)}
        task.node_status = _initial_node_status()
        task.node_status['total_rounds'] = keep['total_rounds']
        task.node_status['success_rounds'] = keep['success_rounds']
    task.member_status = _initial_member_status()


def reset_layer_status(task: TriggerTask):
    """重置层状态：保留通关计数和任务统计，第一主战员状态不受影响。"""
    ns = getattr(task, 'node_status', None)
    if ns is not None:
        keep = {'pass_final_boss_count': ns.get('pass_final_boss_count', 0),
                'total_rounds': ns.get('total_rounds', 0),
                'success_rounds': ns.get('success_rounds', 0)}
        task.node_status = _initial_node_status()
        task.node_status['pass_final_boss_count'] = keep['pass_final_boss_count']
        task.node_status['total_rounds'] = keep['total_rounds']
        task.node_status['success_rounds'] = keep['success_rounds']


def handle_close_button(task: TriggerTask):
    """通用关闭按钮: 检测到关闭按钮则点击关闭。"""
    box = find_box_at_point(task, 0.512, 0.929)
    if box and box.name == "关闭":
        task.log_info("检测到关闭按钮，点击关闭")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_card_assign(task: TriggerTask):
    """卡牌分配页面: 按奖励优先级刷新或跳过，并优先分配给第一主战员。"""
    title_box = find_box_at_point(task, 0.863, 0.133)
    if not (title_box and "请选择要接受卡牌的主战员" in title_box.name):
        return False

    task.log_info("检测到卡牌分配页面")

    card_name_box = find_box_at_point(task, 0.184, 0.272)
    card_name = card_name_box.name.strip() if card_name_box else ""
    card_desc = _get_region_text(task, (0.118, 0.349, 0.324, 0.807))
    task.log_info(f"待分配卡牌: 名称=「{card_name}」，描述=「{card_desc}」")

    bottom_boxes = [
        b for b in task.all_texts
        if 0.290 <= (b.x + b.width / 2) / task.width <= 0.998
        and 0.878 <= (b.y + b.height / 2) / task.height <= 0.997
    ]
    refresh_box = next((b for b in bottom_boxes if "刷新" in b.name), None)
    skip_box = next((b for b in bottom_boxes if "跳过" in b.name), None)
    refresh_count = None
    for bottom_box in bottom_boxes:
        count_match = re.search(r'(\d+)/(\d+)', bottom_box.name)
        if count_match:
            refresh_count = (int(count_match.group(1)), int(count_match.group(2)))
            break

    priority = _get_card_reward_priority(task)
    matched_card_name = next(
        (config_name for config_name in priority
         if card_name and config_name
         and (config_name in card_name or card_name in config_name)),
        None,
    )
    if matched_card_name:
        task.log_info(f"卡牌「{card_name}」命中奖励优先级「{matched_card_name}」")
    else:
        task.log_info(f"卡牌「{card_name}」未命中奖励优先级")
        if refresh_box and refresh_count and refresh_count[0] > 0:
            task.log_info(f"剩余刷新次数: {refresh_count[0]}/{refresh_count[1]}，点击刷新")
            task.click_box(refresh_box)
            return True
        if _get_config_value(task, '跳过非优先级卡牌', True) and skip_box:
            task.log_info("无可用刷新或刷新次数，点击跳过非优先级卡牌")
            task.click_box(skip_box)
            return True

    px1, py1 = int(0.426 * task.width), int(0.292 * task.height)
    px2, py2 = int(0.473 * task.width), int(0.783 * task.height)
    lv_texts = sorted(
        [b for b in task.all_texts
         if b.x >= px1 and b.y >= py1 and b.x + b.width <= px2 and b.y + b.height <= py2
         and "等级" in b.name],
        key=lambda b: b.y
    )
    if not lv_texts:
        task.log_info("未找到主战员等级信息")
        return False

    available_members = []
    for index, level_box in enumerate(lv_texts):
        level_center_x = (level_box.x + level_box.width / 2) / task.width
        level_center_y = (level_box.y + level_box.height / 2) / task.height
        unavailable_box = find_box_at_point(
            task,
            level_center_x + 0.0615,
            level_center_y - 0.0795,
        )
        if unavailable_box and "无法获得" in unavailable_box.name:
            task.log_info(f"第{index + 1}号主战员无法获得该卡牌，排除")
            continue
        available_members.append((index, level_box))

    if not available_members:
        task.log_info("所有主战员均无法获得该卡牌")
        if skip_box:
            task.log_info("尝试点击跳过")
            task.click_box(skip_box)
            return True
        task.log_info("未找到跳过按钮")
        return False

    chosen_idx, chosen_lv = available_members[0]
    task.log_info(f"优先选择第{chosen_idx + 1}号主战员接受卡牌")
    if chosen_idx == 0:
        deck = _member_deck_state(task)
        deck[matched_card_name or card_name] = card_desc
    task.click(0.756, (chosen_lv.y + chosen_lv.height / 2) / task.height)
    task.sleep(1)
    return False

def handle_held_cards_page(task: TriggerTask):
    """持有卡牌页面: 检测到持有卡牌则关闭页面。"""
    box = find_box_at_point(task, 0.500, 0.056)
    if box and box.name == _get_game_text(task, '持有卡牌'):
        task.log_info("检测到持有卡牌页面，点击关闭")
        task.click(0.966, 0.053)
        return True
    return False

def handle_weakness_info(task: TriggerTask):
    """怪物信息页面: 检测到弱点信息则关闭页面。"""
    box = find_box_at_point(task, 0.387, 0.107)
    if box and "弱点" in box.name:
        task.log_info("检测到怪物信息页面，点击关闭")
        task.click(0.502, 0.092)
        return True
    return False

def handle_minimizemap(task: TriggerTask):
    """地图页面: 检测到小地图按钮则点击关闭小地图。"""
    boxes = task.find_feature(feature_name="minimizemap")
    if boxes:
        task.log_info("检测到地图页面，点击关闭小地图")
        task.click_box(boxes[0])
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

def handle_unknown_page(task: TriggerTask):
    """检测到待确认的未知页面: 确认按钮不可点击时随机点击页面中央区域。"""
    box = find_box_at_point(task, 0.916, 0.931)
    if box and _clean_match(box.name, "确认") and not is_button_active(task, box):
        task.log_info("检测到待确认的未知页面，确认按钮不可点击，随机点击页面区域")
        import random
        rx = random.uniform(0.043, 0.972)
        ry = random.uniform(0.149, 0.843)
        task.click(rx, ry)
        task.sleep(1)
        return True
    return False
