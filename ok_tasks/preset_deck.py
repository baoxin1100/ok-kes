"""预设卡组：灵光一闪 / 神闪页面的选择策略（实验模式专用）。

一条记录代表一张卡；同名同效果的记录有几条，就希望牌组里有几张。
匹配顺序：卡牌名 → 卡牌效果 → 神闪效果。
神闪大图标只用来判断“这张卡是不是神闪形态”，并帮助定位它后面那行文本；
不再单独处理 4 张卡的神之效果页，也不再用左侧圆环。
"""
import os
import random
import re
import time
from types import SimpleNamespace

import cv2
import numpy as np

from ok import TriggerTask

from utils import (
    _edit_distance,
    _get_config_value,
    _get_game_text,
    _get_region_text,
    _move_and_click,
    _normalize_text,
    _point_is_white,
    _scroll_card_page,
    _simplify_texts,
    find_box_at_point,
    find_text,
    handle_view_original,
    is_subsequence,
    recognize_cards,
    recognize_cards_in_deck,
)

# 参考截图（灵光一闪界面.png）的游戏画面宽度，用于把模板缩放到当前分辨率。
REFERENCE_WIDTH = 1762.0
ASSET_FOLDER = os.path.join(os.path.dirname(__file__), "assets")
_DECK_PAGE_NAME = "所有牌堆"
_DECK_CACHE_SECONDS = 15
_BIG_ICON_THRESHOLD = 0.83

_TEMPLATE_CACHE = {}
_BIG_TEMPLATE_CACHE = {}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _imread_unicode(path):
    """cv2.imread 不支持中文路径，这里用 imdecode 读取。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _load_template(name):
    if name not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[name] = _imread_unicode(os.path.join(ASSET_FOLDER, name))
    return _TEMPLATE_CACHE[name]


def _compact(text):
    """去掉空白和标点，保留中文、字母、数字，便于 OCR 容错比较。"""
    if text is None:
        return ""
    text = _normalize_text(str(text))
    return re.sub(r"[\s\W_]+", "", text).lower()


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result
    return []


def _text_matches(keyword, text):
    """关键字是否命中文本：优先包含，其次子序列，最后允许 1 个字的 OCR 误差。"""
    keyword = _compact(keyword)
    text = _compact(text)
    if not keyword or not text:
        return False
    if keyword in text:
        return True
    if is_subsequence(keyword, text):
        return True
    if len(keyword) >= 4 and abs(len(keyword) - len(text)) <= 2:
        return _edit_distance(keyword, text, 1)
    return False


def _name_matches(first, second):
    first = _compact(first)
    second = _compact(second)
    if not first or not second:
        return False
    if first in second or second in first:
        return True
    if is_subsequence(first, second) or is_subsequence(second, first):
        return True
    if min(len(first), len(second)) >= 3:
        return _edit_distance(first, second, 1)
    return False


# ---------------------------------------------------------------------------
# 预设数据
# ---------------------------------------------------------------------------

def _normalize_record(raw):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "") or "").strip()
    if not name:
        return None
    effects = _as_list(raw.get("effects"))
    if not effects:
        effects = _as_list(raw.get("effect"))
    divine_text = _as_list(raw.get("divine_text"))
    if not divine_text:
        divine_text = _as_list(raw.get("special"))
    reject = raw.get("reject_divine")
    if reject is None:
        reject = raw.get("reject_flash", False)
    record = {
        "name": name,
        "effects": effects,
        "divine_text": divine_text,
        "reject_divine": bool(reject),
    }
    notes = _as_list(raw.get("import_notes"))
    if notes:
        record["import_notes"] = notes
    return record


def load_preset_records(task):
    """读取当前任务的预设卡组，过滤无效记录。"""
    if hasattr(task, "config") and isinstance(getattr(task, "config", None), dict):
        raw = task.config.get("预设卡组")
    else:
        raw = None
    if raw is None:
        raw = getattr(task, "default_config", {}).get("预设卡组", [])
    if not isinstance(raw, (list, tuple)):
        return []
    records = []
    for item in raw:
        record = _normalize_record(item)
        if record:
            records.append(record)
    return records


def _record_key(record):
    effects = tuple(_compact(effect) for effect in record.get("effects", []))
    return (_compact(record.get("name", "")), effects)


def build_groups(records):
    """按“卡牌名 + 效果关键字”分组；组内记录数就是希望获得的张数。"""
    groups = []
    index = {}
    for record in records:
        key = _record_key(record)
        if key not in index:
            group = {
                "key": key,
                "name": record["name"],
                "effects": record["effects"],
                "records": [],
            }
            index[key] = group
            groups.append(group)
        index[key]["records"].append(record)
    for group in groups:
        group["size"] = len(group["records"])
    return groups


def convert_legacy_flash_priority(value):
    """把旧版“闪光优先级”转换为预设卡组记录（一条旧配置 = 一张卡）。"""
    if isinstance(value, str):
        try:
            import json
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        entries = []
        for card_name, descriptions in value.items():
            if not isinstance(card_name, str):
                continue
            for description in descriptions if isinstance(descriptions, (list, tuple)) else []:
                if isinstance(description, str) and description:
                    entries.append(f"{card_name}：{description}")
        value = entries
    if not isinstance(value, (list, tuple)):
        return []
    records = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        entry = entry.strip()
        if not entry:
            continue
        name = entry
        effect = entry
        if "：" in entry:
            name, effect = entry.split("：", 1)
        elif ":" in entry:
            name, effect = entry.split(":", 1)
        else:
            parts = entry.split(None, 1)
            if len(parts) == 2:
                name, effect = parts
        name = name.strip()
        effect = effect.strip()
        if not name:
            continue
        records.append({
            "name": name,
            "effects": [effect or name],
            "divine_text": [],
            "reject_divine": False,
        })
    return records


# ---------------------------------------------------------------------------
# 卡牌匹配
# ---------------------------------------------------------------------------

def _card_name(card):
    return card.get("name", "") if isinstance(card, dict) else ""


def _card_description(card):
    return card.get("description", "") if isinstance(card, dict) else ""


def _compact_index_to_original(text, compact_index):
    """把 _compact 后的下标映射回原文本下标。"""
    mapping = []
    compact_chars = []
    for index, char in enumerate(text):
        normalized = _normalize_text(char)
        if not normalized or normalized.isspace() or normalized == "_":
            continue
        if not re.match(r"[\u4e00-\u9fff\w]", normalized, re.UNICODE):
            continue
        compact_chars.append(normalized.lower())
        mapping.append(index)
    if 0 <= compact_index < len(mapping):
        return mapping[compact_index]
    return len(text)


def _card_effect_text(task, card, records=None):
    """只返回卡牌效果文本，剔除神闪效果，供冥想判断使用。"""
    text = _card_description(card)
    if not text:
        return ""
    name = _card_name(card)
    if records is None:
        records = load_preset_records(task)
    for record in records or []:
        if not _name_matches(record.get("name", ""), name):
            continue
        for divine in record.get("divine_text") or []:
            divine = str(divine).strip()
            if len(divine) < 2:
                continue
            if divine in text:
                text = text.replace(divine, "")
                continue
            compact_text = _compact(text)
            compact_divine = _compact(divine)
            if compact_divine and compact_divine in compact_text:
                start = _compact_index_to_original(
                    text, compact_text.find(compact_divine)
                )
                if 0 <= start < len(text):
                    text = text[:start]
    return text.strip()


def _record_effect_hits(record, card):
    effects = record.get("effects") or []
    if not effects:
        return True
    description = _card_description(card)
    return any(_text_matches(effect, description) for effect in effects)


def _record_name_hits(record, card):
    return _name_matches(record.get("name", ""), _card_name(card))


def _record_divine_hits(record, text):
    keywords = record.get("divine_text") or []
    if not keywords:
        return False
    return any(_text_matches(keyword, text) for keyword in keywords)


def _group_card_hits(group, card):
    if not _name_matches(group["name"], _card_name(card)):
        return False
    return _record_effect_hits(group["records"][0], card)


# ---------------------------------------------------------------------------
# 神闪大图标（卡牌名字下方左侧的小盾牌）
# ---------------------------------------------------------------------------

def _load_big_template(icon_id):
    if icon_id not in _BIG_TEMPLATE_CACHE:
        rgb = _imread_unicode(os.path.join(ASSET_FOLDER, "divine_big", f"{icon_id}.png"))
        mask_data = None
        try:
            mask_data = np.fromfile(
                os.path.join(ASSET_FOLDER, "divine_big", f"{icon_id}_mask.png"),
                dtype=np.uint8,
            )
            mask = cv2.imdecode(mask_data, cv2.IMREAD_GRAYSCALE)
        except Exception:
            mask = None
        _BIG_TEMPLATE_CACHE[icon_id] = (rgb, mask)
    return _BIG_TEMPLATE_CACHE[icon_id]


def _big_icon_region(task, card):
    """神闪大图标在卡牌名字下方、类型图标左侧。"""
    box = card.get("feature_box")
    if box is None:
        return None
    width = getattr(task, "width", 0) or 0
    height = getattr(task, "height", 0) or 0
    if width <= 0 or height <= 0:
        return None
    fx = box.x / width
    fy = box.y / height
    fw = getattr(box, "width", 0) / width
    fh = getattr(box, "height", 0) / height
    x1 = max(0.0, fx - 0.006)
    x2 = min(1.0, fx + fw + 0.006)
    y1 = max(0.0, fy - 0.006)
    y2 = min(1.0, fy + fh + 0.018)
    if x2 - x1 < 0.04 or y2 - y1 < 0.04:
        return None
    return (x1, y1, x2, y2)


def _big_icon_score(task, card):
    """返回 (最高分, 最像的标志编号)；分数低于阈值表示没有神闪大图标。"""
    frame = getattr(task, "frame", None)
    region = _big_icon_region(task, card)
    if frame is None or region is None:
        return 0.0, 0
    height, width = frame.shape[:2]
    x1 = max(0, min(width, int(round(region[0] * width))))
    y1 = max(0, min(height, int(round(region[1] * height))))
    x2 = max(x1 + 1, min(width, int(round(region[2] * width))))
    y2 = max(y1 + 1, min(height, int(round(region[3] * height))))
    roi = frame[y1:y2, x1:x2, :3]
    if roi.size == 0:
        return 0.0, 0
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))
    if edges.size == 0:
        return 0.0, 0

    base = (width or REFERENCE_WIDTH) / REFERENCE_WIDTH
    best_score = 0.0
    best_icon = 0
    for icon_id in range(1, 7):
        template, mask = _load_big_template(icon_id)
        if template is None or mask is None:
            continue
        for factor in (0.30, 0.36, 0.42, 0.48, 0.54, 0.60, 0.66, 0.72, 0.80, 0.90):
            scale = base * factor
            if scale <= 0:
                continue
            tw = max(1, int(round(template.shape[1] * scale)))
            th = max(1, int(round(template.shape[0] * scale)))
            if th > roi.shape[0] or tw > roi.shape[1]:
                continue
            scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
            scaled_mask = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST)
            template_edges = cv2.Canny(
                cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY), 50, 150
            )
            template_edges = cv2.dilate(
                template_edges, np.ones((2, 2), np.uint8)
            )
            if int(template_edges.sum()) == 0:
                continue
            try:
                result = cv2.matchTemplate(
                    edges,
                    template_edges,
                    cv2.TM_CCORR_NORMED,
                    mask=(scaled_mask > 0).astype(np.uint8) * 255,
                )
            except cv2.error:
                continue
            result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, max_value, _, _ = cv2.minMaxLoc(result)
            if max_value > best_score:
                best_score = float(max_value)
                best_icon = icon_id
    return best_score, best_icon


def _card_has_big_divine(task, card):
    if "_has_big_divine" in card:
        return bool(card["_has_big_divine"])
    score, icon_id = _big_icon_score(task, card)
    has_icon = score >= _BIG_ICON_THRESHOLD
    card["_has_big_divine"] = has_icon
    card["_big_icon_score"] = score
    card["_big_icon_type"] = icon_id
    task.log_info(
        f"预设卡组: 「{_card_name(card)}」神闪大图标检测="
        f"{'有' if has_icon else '无'}（最像标志{icon_id}，相似度{score:.3f}）"
    )
    return has_icon


# ---------------------------------------------------------------------------
# 冥想候选（按实际牌组效果判断）
# ---------------------------------------------------------------------------

def _group_effect(group):
    effects = group.get("effects") or []
    return effects[0] if effects else ""


def _effect_matches(target, current):
    """目标效果和当前效果是否算同一个（允许卡面短文本是目标效果的前缀）。"""
    if _text_matches(target, current):
        return True
    target_text = _compact(target)
    current_text = _compact(current)
    return (
        len(current_text) >= 4
        and current_text in target_text
    )


def _target_effect_for(task, name, current_effect, groups, counts):
    """返回同名卡里第一个“效果不同且数量还缺”的目标效果；没有则 None。"""
    name_groups = [
        group for group in groups if _name_matches(group.get("name", ""), name)
    ]
    for group in name_groups:
        effect = _group_effect(group)
        if effect and _effect_matches(effect, current_effect):
            return None
        if counts.get(group["key"], 0) < group.get("size", 0):
            return effect
    return None


def _add_meditation_pending(task, name, current_effect, target_effect):
    if not name or not target_effect:
        return
    pending = getattr(task, "_preset_meditation_pending", None)
    if not isinstance(pending, list):
        pending = []
        task._preset_meditation_pending = pending
    key = (_compact(name), _compact(current_effect), _compact(target_effect))
    for item in pending:
        if (
            _compact(item.get("name", "")),
            _compact(item.get("current_effect", "")),
            _compact(item.get("target_effect", "")),
        ) == key:
            return
    pending.append(
        {
            "name": name,
            "current_effect": current_effect,
            "target_effect": target_effect,
        }
    )
    task.log_info(
        f"预设卡组: 冥想候选「{name}」当前效果=「{current_effect}」，"
        f"目标效果=「{target_effect}」"
    )


def _rebuild_meditation_pending(task, cards, group_counts=None):
    """按读到的牌组卡牌，重建待冥想列表（效果不同且目标数量还缺）。"""
    records = load_preset_records(task)
    if not records:
        task._preset_meditation_pending = []
        return
    groups = build_groups(records)
    counts = (
        group_counts
        if isinstance(group_counts, dict)
        else {group["key"]: _count_group_cards(cards, group) for group in groups}
    )
    pending = []
    task._preset_meditation_pending = pending
    for card in cards:
        name = _card_name(card)
        if not name:
            continue
        name_groups = [
            group for group in groups if _name_matches(group.get("name", ""), name)
        ]
        if not name_groups:
            continue
        description = _card_effect_text(task, card, records)
        if any(_effect_matches(_group_effect(group), description) for group in name_groups):
            continue
        target = None
        for group in name_groups:
            if counts.get(group["key"], 0) < group.get("size", 0):
                target = _group_effect(group)
                break
        if target:
            _add_meditation_pending(task, name, description, target)


def _add_pending_for_card(task, card):
    """选到/复制到/商店买到一张效果可能不对的卡后，按预设补一条待冥想。"""
    if not isinstance(card, dict):
        return
    name = _card_name(card)
    description = _card_description(card)
    if not name or not description:
        return
    records = load_preset_records(task)
    if not records:
        return
    description = _card_effect_text(task, card, records)
    if not description:
        return
    groups = build_groups(records)
    cached = getattr(task, "_preset_deck_cache", None)
    counts = cached if isinstance(cached, dict) else {}
    target = _target_effect_for(task, name, description, groups, counts)
    if target:
        _add_meditation_pending(task, name, description, target)


# ---------------------------------------------------------------------------
# 冥想选卡/选效果页面
# ---------------------------------------------------------------------------

_MEDITATION_TIMEOUT = 10.0


def _find_meditation_box(task, keyword):
    if not keyword:
        return None
    keyword = _compact(keyword)
    for box in task.all_texts:
        text = _compact(getattr(box, "name", ""))
        if not text:
            continue
        if keyword in text or (len(text) >= 4 and text in keyword):
            return box
    return None


def _click_text_box(task, box):
    _move_and_click(
        task,
        (box.x + box.width / 2) / task.width,
        (box.y + box.height / 2) / task.height,
    )


def handle_preset_meditation_choice(task: TriggerTask):
    """冥想页：选择目标效果；目标效果没出现就跳过，保留待冥想。"""
    if not getattr(task, "preset_deck_enabled", False):
        return False
    if not getattr(task, "_preset_meditation_active", False):
        return False
    pending = getattr(task, "_preset_meditation_pending", None)
    if not isinstance(pending, list) or not pending:
        task._preset_meditation_active = False
        return False
    if time.time() - getattr(task, "_preset_meditation_page_time", 0) > _MEDITATION_TIMEOUT:
        task.log_info("预设卡组: 冥想页等待超时，保留待冥想")
        task._preset_meditation_active = False
        return False

    # 只有冥想页面才处理，避免休息页的“跳过”被误点。
    title = _get_region_text(task, (0.30, 0.05, 0.70, 0.18))
    if "冥想" not in title:
        return False

    task.all_texts = _simplify_texts(task.ocr())
    item = pending[0]
    target = item.get("target_effect", "")
    target_box = _find_meditation_box(task, target)
    if target_box is None:
        card_box = _find_meditation_box(task, item.get("name", ""))
        if card_box is not None:
            task.log_info(f"预设卡组: 冥想页选择卡牌「{item.get('name', '')}」")
            _click_text_box(task, card_box)
            task.sleep(0.8)
            task.all_texts = _simplify_texts(task.ocr())
            target_box = _find_meditation_box(task, target)

    if target_box is not None:
        task.log_info(f"预设卡组: 冥想页选择目标效果「{target}」")
        _click_text_box(task, target_box)
        task.sleep(0.8)
        task.all_texts = _simplify_texts(task.ocr())
        confirm = next(
            (
                box
                for box in task.all_texts
                if "确认" in box.name or "确定" in box.name
            ),
            None,
        )
        if confirm is not None:
            task.click_box(confirm)
            task.sleep(0.8)
        pending.remove(item)
        task._preset_meditation_active = False
        try:
            for group in build_groups(load_preset_records(task)):
                if _name_matches(group.get("name", ""), item.get("name", "")) and _text_matches(
                    _group_effect(group), target
                ):
                    cache = getattr(task, "_preset_deck_cache", None)
                    if isinstance(cache, dict):
                        cache[group["key"]] = cache.get(group["key"], 0) + 1
                    break
        except Exception:
            pass
        task.log_info(
            f"预设卡组: 冥想完成「{item.get('name', '')}」→「{target}」"
        )
        return True

    cancel = next(
        (
            box
            for box in task.all_texts
            if "取消" in box.name or "返回" in box.name or "跳过" in box.name
        ),
        None,
    )
    if cancel is not None:
        task.log_info("预设卡组: 冥想页没有目标效果，跳过本次冥想，保留待冥想")
        task.click_box(cancel)
        task.sleep(0.5)
        task._preset_meditation_active = False
        return True
    return False


# ---------------------------------------------------------------------------
# 牌组读取
# ---------------------------------------------------------------------------

def _find_deck_icon(task):
    """在灵光一闪页面左下角找“查看牌组”的 D 图标。"""
    frame = getattr(task, "frame", None)
    if frame is None:
        return None
    template = _load_template("view_deck_icon.png")
    if template is None:
        return None
    height, width = frame.shape[:2]
    search = (0.015, 0.845, 0.190, 0.995)
    x1 = max(0, int(search[0] * width))
    y1 = max(0, int(search[1] * height))
    x2 = min(width, int(search[2] * width))
    y2 = min(height, int(search[3] * height))
    roi = frame[y1:y2, x1:x2, :3]
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    best = (0.0, None)
    for scale in (0.92, 1.0, 1.08):
        scaled = cv2.resize(
            template,
            (max(1, int(round(template.shape[1] * scale * width / REFERENCE_WIDTH))),
             max(1, int(round(template.shape[0] * scale * width / REFERENCE_WIDTH)))),
            interpolation=cv2.INTER_AREA,
        )
        if scaled.shape[0] > gray.shape[0] or scaled.shape[1] > gray.shape[1]:
            continue
        template_gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        try:
            result = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
        except cv2.error:
            continue
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        if max_value > best[0]:
            best = (
                float(max_value),
                (
                    (x1 + max_location[0] + scaled.shape[1] / 2) / width,
                    (y1 + max_location[1] + scaled.shape[0] / 2) / height,
                ),
            )
    if best[0] >= 0.60 and best[1] is not None:
        task.log_info(f"预设卡组: 找到查看牌组图标，相似度={best[0]:.4f}，位置={best[1]}")
        return best[1]
    return None


def _is_deck_page(task):
    if find_text(task, _DECK_PAGE_NAME):
        return True
    return _DECK_PAGE_NAME in _get_region_text(task, (0.08, 0.035, 0.42, 0.130))


def _open_deck_page(task):
    """点击查看牌组图标并等待“所有牌堆”页面。"""
    for attempt in range(2):
        position = _find_deck_icon(task)
        if position is None:
            position = (0.091, 0.928)
            task.log_info("预设卡组: 未匹配到查看牌组图标，使用固定坐标(0.091, 0.928)")
        _move_and_click(task, position[0], position[1])
        task.sleep(0.6)
        for _ in range(14):
            task.all_texts = _simplify_texts(task.ocr())
            if _is_deck_page(task):
                task.log_info("预设卡组: 已进入所有牌堆页面")
                return True
            task.sleep(0.35)
        task.log_info(f"预设卡组: 第{attempt + 1}次未能打开牌组页面")
    return False


def _close_deck_page(task):
    """关闭所有牌堆页面，回到灵光一闪页面。"""
    close_box = None
    try:
        close_box = task.find_one(
            "close_page",
            box=task.box_of_screen(0.90, 0.02, 0.995, 0.10),
            threshold=0.60,
        )
    except Exception:
        close_box = None
    if close_box is not None:
        task.log_info("预设卡组: 点击右上角关闭按钮")
        task.click_box(close_box)
    else:
        _move_and_click(task, 0.956, 0.055)
    for _ in range(10):
        task.sleep(0.35)
        task.all_texts = _simplify_texts(task.ocr())
        if not _is_deck_page(task):
            task.log_info("预设卡组: 已关闭所有牌堆页面")
            task.sleep(0.3)
            return True
    task.log_info("预设卡组: 关闭按钮未生效，尝试按 ESC")
    try:
        task.send_key("esc")
        task.sleep(0.5)
        task.all_texts = _simplify_texts(task.ocr())
    except Exception as exc:
        task.log_warning(f"预设卡组: 按 ESC 关闭牌组页面失败: {exc}")
    return not _is_deck_page(task)


def _count_group_cards(cards, group):
    return sum(1 for card in cards if _group_card_hits(group, card))


def _deck_member_levels(task):
    """返回所有主战员头像的“等级”文字框，以及目标主战员所在段的序号。"""
    levels = [
        box
        for box in task.all_texts
        if "等级" in (getattr(box, "name", "") or "")
        or "等級" in (getattr(box, "name", "") or "")
    ]
    levels.sort(key=lambda box: box.y)
    target_index = 0
    target_member = _get_config_value(task, "刷存档主战员", "") or ""
    if levels and target_member:
        for box in task.all_texts:
            if not _name_matches(target_member, getattr(box, "name", "")):
                continue
            close = [
                index
                for index, level in enumerate(levels)
                if abs(level.y - box.y) < 0.15 * (task.height or 1)
            ]
            if close:
                target_index = close[0]
            break
    return levels, target_index


def _filter_deck_member_section(task, cards, levels, target_index):
    """只保留目标主战员那一段的卡牌；返回 (卡牌, 是否看到下一个主战员)。"""
    if not levels:
        return cards, False
    height = task.height or 1
    start_y = max(0.0, (levels[target_index].y - 0.32 * height) / height)
    end_y = None
    reached_next = False
    if target_index + 1 < len(levels):
        end_y = max(0.0, (levels[target_index + 1].y - 0.30 * height) / height)
        reached_next = True
    filtered = []
    for card in cards:
        feature_box = card.get("feature_box")
        if feature_box is None:
            continue
        card_y = feature_box.y / height
        if card_y < start_y:
            continue
        if end_y is not None and card_y >= end_y:
            continue
        filtered.append(card)
    return filtered, reached_next


_DECK_MEMBER_ICON_CACHE = None


def _load_deck_member_icon():
    global _DECK_MEMBER_ICON_CACHE
    if _DECK_MEMBER_ICON_CACHE is None:
        path = os.path.join(ASSET_FOLDER, "deck_member_icon.png")
        try:
            data = np.fromfile(path, dtype=np.uint8)
            _DECK_MEMBER_ICON_CACHE = cv2.imdecode(data, cv2.IMREAD_COLOR)
        except Exception:
            _DECK_MEMBER_ICON_CACHE = False
    return _DECK_MEMBER_ICON_CACHE


def _deck_member_icon_tops(task):
    """匹配主战员头像左侧的牌堆小图标，返回各段顶部的归一化 y。"""
    template = _load_deck_member_icon()
    if template is None or getattr(template, "size", 0) == 0:
        return []
    if getattr(template, "shape", None) is None:
        return []
    frame = getattr(task, "frame", None)
    if frame is None:
        return []
    height, width = frame.shape[:2]
    if not width or not height:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    x1, y1 = int(0.07 * width), int(0.05 * height)
    x2, y2 = int(0.95 * width), int(0.99 * height)
    roi = gray[y1:y2, x1:x2]
    base_scale = width / REFERENCE_WIDTH
    found = []
    for factor in (0.9, 1.0, 1.1):
        scale = base_scale * factor
        resized = cv2.resize(
            cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
            (max(1, int(template.shape[1] * scale)), max(1, int(template.shape[0] * scale))),
        )
        if resized.shape[0] >= roi.shape[0] or resized.shape[1] >= roi.shape[1]:
            continue
        result = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= 0.70)
        for y, x in zip(ys, xs):
            center_y = (y1 + y + resized.shape[0] / 2) / height
            score = float(result[y, x])
            if all(abs(center_y - old_y) > 0.04 for old_y, _ in found):
                found.append((center_y, score))
            elif score > next(s for old_y, s in found if abs(center_y - old_y) <= 0.04):
                found = [
                    (old_y, score if abs(center_y - old_y) <= 0.04 else old_score)
                    for old_y, old_score in found
                ]
    return sorted(y for y, _ in found)


def _target_member_y(task):
    """目标主战员名字的归一化 y；用于区分“自己这一段”和“下一段”。"""
    target_member = _get_config_value(task, "刷存档主战员", "") or ""
    if not target_member:
        return None
    for box in task.all_texts:
        if _name_matches(target_member, getattr(box, "name", "")):
            return (box.y + box.height / 2) / (task.height or 1)
    return None


def _filter_deck_by_member_icon(task, cards, icon_tops, target_y):
    """用主战员图标截断：目标主战员名字下方第一个图标就是下一段。"""
    if not icon_tops:
        return cards, False
    threshold = (target_y + 0.04) if target_y is not None else 0.25
    next_icon = next((y for y in icon_tops if y > threshold), None)
    if next_icon is None:
        return cards, False
    end_y = max(0.0, next_icon - 0.03)
    height = task.height or 1
    filtered = []
    for card in cards:
        feature_box = card.get("feature_box")
        if feature_box is None:
            continue
        if feature_box.y / height < end_y:
            filtered.append(card)
    return filtered, True


_COMBATANT_PARTY_POINT = (0.10, 0.09)
# 战斗员界面左侧牌堆图标：截图红框中心 (75, 312)，去掉32px标题栏后相对游戏内容为 (0.042, 0.283)
_COMBATANT_DECK_POINT = (0.042, 0.283)
_COMBATANT_CLOSE_POINT = (0.96, 0.050)


def _is_combatant_page(task):
    title = _get_region_text(task, (0.10, 0.02, 0.90, 0.13))
    return any(word in title for word in ("战斗员", "伙伴", "命运"))


def _open_all_decks_from_any_page(task):
    """从休息/商店页进战斗员界面，再进所有牌堆。"""
    task.all_texts = _simplify_texts(task.ocr())
    if _is_deck_page(task):
        return True

    on_combatant = _is_combatant_page(task)
    if not on_combatant:
        _move_and_click(task, *_COMBATANT_PARTY_POINT)
        entered = False
        for _ in range(10):
            task.sleep(0.4)
            task.all_texts = _simplify_texts(task.ocr())
            if _is_combatant_page(task):
                entered = True
                break
        if not entered:
            return _open_deck_page(task)
        on_combatant = True

    _move_and_click(task, *_COMBATANT_DECK_POINT)
    for _ in range(15):
        task.sleep(0.4)
        task.all_texts = _simplify_texts(task.ocr())
        if _is_deck_page(task):
            task.log_info("预设卡组: 已从战斗员界面进入所有牌堆")
            return True
    task.log_warning("预设卡组: 战斗员界面点击牌堆图标后未进入所有牌堆")
    if on_combatant or _is_combatant_page(task):
        for _ in range(2):
            _move_and_click(task, *_COMBATANT_CLOSE_POINT)
            task.sleep(0.8)
            task.all_texts = _simplify_texts(task.ocr())
            if not _is_combatant_page(task):
                break
    return False


def _close_all_decks_page(task):
    _close_deck_page(task)
    task.sleep(0.5)
    task.all_texts = _simplify_texts(task.ocr())
    if _is_combatant_page(task):
        _move_and_click(task, *_COMBATANT_CLOSE_POINT)
        for _ in range(8):
            task.sleep(0.4)
            task.all_texts = _simplify_texts(task.ocr())
            if not _is_combatant_page(task):
                break


def read_removal_deck_counts(task, targets=None, prefer_base=True, extra_names=None):
    """从所有牌堆读取移除目标/基础牌数量；可顺便读预设卡名数量。"""
    targets = list(
        dict.fromkeys(
            str(name).strip()
            for name in (targets or [])
            if str(name).strip()
        )
    )
    extra_names = list(
        dict.fromkeys(
            str(name).strip()
            for name in (extra_names or [])
            if str(name).strip()
        )
    )
    if not targets and not prefer_base and not extra_names:
        return {}
    if not _open_all_decks_from_any_page(task):
        task.log_warning("预设卡组: 无法从当前页面打开所有牌堆")
        return None

    counts = {name: 0 for name in targets}
    extra_counts = {name: 0 for name in extra_names}
    basic_count = 0
    base_card_type = _get_game_text(task, "基础")
    try:
        task.sleep(0.5)
        for _ in range(10):
            task.all_texts = _simplify_texts(task.ocr())
            cards = recognize_cards_in_deck(task, page=_DECK_PAGE_NAME)
            if not cards:
                break
            icon_tops = _deck_member_icon_tops(task)
            target_y = _target_member_y(task)
            filtered, reached_next = _filter_deck_by_member_icon(
                task, cards, icon_tops, target_y
            )
            for name in targets:
                count = sum(
                    1 for card in filtered if _name_matches(name, _card_name(card))
                )
                counts[name] = max(counts[name], count)
            for name in extra_names:
                count = sum(
                    1 for card in filtered if _name_matches(name, _card_name(card))
                )
                extra_counts[name] = max(extra_counts[name], count)
            if prefer_base:
                basic_count = max(
                    basic_count,
                    sum(
                        1
                        for card in filtered
                        if base_card_type in card.get("type", "")
                    ),
                )
            if reached_next:
                break
            # 目标段如果没有结束图标，当前首屏读完即可，宁少算不多算。
            break
    finally:
        _close_all_decks_page(task)

    result = dict(counts)
    result.update(extra_counts)
    if prefer_base:
        result["__basic__"] = basic_count
    task.log_info(
        f"预设卡组: 所有牌堆移除/预设目标数量={result}"
    )
    return result


def read_memory_card(task, target_name):
    """从所有牌堆里找指定记忆卡，返回卡牌字典；找不到返回 None。"""
    if not target_name:
        return None
    if not _open_all_decks_from_any_page(task):
        return None
    found = None
    try:
        task.sleep(0.5)
        for _ in range(10):
            task.all_texts = _simplify_texts(task.ocr())
            cards = recognize_cards_in_deck(task, page=_DECK_PAGE_NAME)
            if not cards:
                break
            icon_tops = _deck_member_icon_tops(task)
            target_y = _target_member_y(task)
            filtered, _ = _filter_deck_by_member_icon(task, cards, icon_tops, target_y)
            for card in filtered:
                if _name_matches(target_name, _card_name(card)):
                    found = card
                    break
            if found:
                break
            break
    finally:
        _close_all_decks_page(task)
    return found


def _read_deck_counts(task, groups):
    """打开牌组并统计候选分组在当前牌组中的数量（每个分组取单屏最大数量）。"""
    if not groups:
        return {}
    cached = getattr(task, "_preset_deck_cache", None)
    cached_time = getattr(task, "_preset_deck_cache_time", 0)
    if (
        isinstance(cached, dict)
        and time.time() - cached_time <= _DECK_CACHE_SECONDS
        and all(group["key"] in cached for group in groups)
    ):
        task.log_info("预设卡组: 复用本次灵光一闪的牌组统计缓存")
        return cached

    if not _open_deck_page(task):
        task.log_warning("预设卡组: 无法打开牌组页面")
        return None

    best = {group["key"]: 0 for group in groups}
    name_counts = {group["name"]: 0 for group in groups}
    all_cards = {}
    previous_signature = None
    unchanged_rounds = 0
    saw_any_card = False
    page = _DECK_PAGE_NAME
    task.sleep(0.6)
    try:
        for step in range(24):
            task.all_texts = _simplify_texts(task.ocr())
            cards = recognize_cards_in_deck(task, page=page)
            reached_next_member = False
            if cards:
                icon_tops = _deck_member_icon_tops(task)
                target_y = _target_member_y(task)
                cards, reached_next_member = _filter_deck_by_member_icon(
                    task, cards, icon_tops, target_y
                )
                if not reached_next_member:
                    levels, target_index = _deck_member_levels(task)
                    cards, reached_next_member = _filter_deck_member_section(
                        task, cards, levels, target_index
                    )
            if cards:
                saw_any_card = True
                for card in cards:
                    key = (
                        _compact(card.get("name", "")),
                        _compact(card.get("description", "")),
                    )
                    all_cards[key] = card
                signature = tuple(
                    sorted(
                        (_compact(card.get("name", "")), _compact(card.get("description", "")))
                        for card in cards
                    )
                )
                for group in groups:
                    count = _count_group_cards(cards, group)
                    if count > best[group["key"]]:
                        best[group["key"]] = count
                        task.log_info(
                            f"预设卡组: 牌组中「{group['name']}」当前至少{count}张"
                        )
                for group in groups:
                    name = group["name"]
                    name_count = sum(
                        1 for card in cards if _name_matches(name, _card_name(card))
                    )
                    if name_count > name_counts.get(name, 0):
                        name_counts[name] = name_count
                if signature == previous_signature:
                    unchanged_rounds += 1
                else:
                    unchanged_rounds = 0
                previous_signature = signature
            else:
                unchanged_rounds += 1

            if reached_next_member:
                task.log_info("预设卡组: 已到下一个主战员的牌堆，停止翻页")
                break
            if all(best[group["key"]] >= group["size"] for group in groups):
                task.log_info("预设卡组: 候选卡牌数量都已满足，停止继续翻页")
                break
            if not saw_any_card and step >= 4:
                task.log_warning(
                    "预设卡组: 牌组页面连续多屏没有识别到卡牌，结束本次统计"
                )
                break
            if unchanged_rounds >= 2 and saw_any_card:
                task.log_info("预设卡组: 连续两屏没有新卡牌，判定已到牌组底部")
                break
            if _point_is_white(task, 0.982, 0.925, page):
                task.log_info("预设卡组: 滚动条已到底部")
                break
            _scroll_card_page(task, 0.620, 0.560, -1, page, distance=0.18)
            task.sleep(0.45)
    finally:
        _close_deck_page(task)

    task._preset_deck_cache = best
    task._preset_deck_cache_time = time.time()
    task._preset_name_counts = name_counts
    _rebuild_meditation_pending(task, list(all_cards.values()), best)
    return best


# ---------------------------------------------------------------------------
# 选卡
# ---------------------------------------------------------------------------

_THREE_CARD_X = (0.23, 0.48, 0.73)


def _ensure_three_cards(task, cards):
    """神闪卡的类型图标会被盾牌替换，特征识别可能只认出 2 张；按三列布局补一张。"""
    if getattr(task, "_preset_flash_page", "") != "divine":
        return cards
    if len(cards) != 2:
        return cards
    known_x = [float(card.get("x", 0) or 0) for card in cards]
    missing = [value for value in _THREE_CARD_X if all(abs(value - x) > 0.08 for x in known_x)]
    if len(missing) != 1:
        return cards
    missing_x = missing[0]
    width = getattr(task, "width", 0) or 0
    height = getattr(task, "height", 0) or 0
    if width <= 0 or height <= 0:
        return cards
    reference = min(cards, key=lambda card: abs(float(card.get("x", 0) or 0) - missing_x))
    dx = missing_x - float(reference.get("x", 0) or 0)

    def shifted_region(region):
        if not region:
            return None
        return (
            max(0.0, region[0] + dx),
            region[1],
            min(1.0, region[2] + dx),
            region[3],
        )

    description_region = shifted_region(reference.get("description_region"))
    description = (
        _get_region_text(task, description_region)
        if description_region
        else reference.get("description", "")
    )
    name_region = shifted_region(reference.get("name_region"))
    type_region = shifted_region(reference.get("type_region"))
    feature_box = reference.get("feature_box")
    synthetic = {
        "name": reference.get("name", ""),
        "type": reference.get("type", ""),
        "description": description,
        "feature_name": reference.get("feature_name", ""),
        "feature_type": reference.get("feature_type", ""),
        "confidence": 0.0,
        "feature_box": SimpleNamespace(
            x=(feature_box.x if feature_box else 0) + dx * width,
            y=(feature_box.y if feature_box else 0),
            width=(feature_box.width if feature_box else 0),
            height=(feature_box.height if feature_box else 0),
        ),
        "x": (name_region[0] + name_region[2]) / 2 if name_region else missing_x,
        "y": (name_region[1] + name_region[3]) / 2 if name_region else 0.30,
        "name_region": name_region,
        "type_region": type_region,
        "description_region": description_region,
        "_synthetic": True,
    }
    task.log_info(
        f"预设卡组: 只识别到 2 张卡，按三列布局补出第 3 张"
        f"（x={synthetic['x']:.3f}）"
    )
    cards.append(synthetic)
    cards.sort(key=lambda card: float(card.get("x", 0) or 0))
    return cards


def _fallback_choice(task, cards):
    """效果/神闪都不符合时：非神闪随机；三张全神闪选第一张。"""
    if not cards:
        return None
    normal_cards = [card for card in cards if not _card_has_big_divine(task, card)]
    if normal_cards:
        choice = random.choice(normal_cards)
        task.log_info(
            f"预设卡组: 按规则回退，在{len(normal_cards)}张非神闪卡中随机选择"
            f"「{_card_name(choice)}」"
        )
        _bump_name_count(task, _card_name(choice))
        _add_pending_for_card(task, choice)
        return choice
    choice = cards[0]
    task.log_info(
        f"预设卡组: 三张都是神闪卡，按规则选择第一张「{_card_name(choice)}」"
    )
    _bump_name_count(task, _card_name(choice))
    _add_pending_for_card(task, choice)
    return choice


def _choose_preset_card(task, cards):
    """供 handle_view_original 调用的选卡函数。"""
    if not cards:
        return None
    cards = _ensure_three_cards(task, cards)
    records = load_preset_records(task)
    if not records:
        return _fallback_choice(task, cards)

    # 预先算好每张卡有没有神闪大图标，后面的回退也要用。
    for card in cards:
        _card_has_big_divine(task, card)

    card_name = _card_name(cards[0])
    name_records = [
        record for record in records if _name_matches(record.get("name", ""), card_name)
    ]
    if not name_records:
        task.log_info(f"预设卡组: 本页卡名「{card_name}」不在预设卡组，按规则回退")
        return _fallback_choice(task, cards)

    groups = build_groups(name_records)
    task.log_info(
        "预设卡组: 本页卡名 "
        + "、".join(f"「{group['name']}」(需{group['size']}张)" for group in groups)
    )
    counts = _read_deck_counts(task, groups)
    if counts is None:
        task.log_info("预设卡组: 读取牌组失败，按规则回退")
        return _fallback_choice(task, cards)

    for group in groups:
        actual = counts.get(group["key"], 0)
        if actual >= group["size"]:
            task.log_info(
                f"预设卡组: 「{group['name']}」牌组已有{actual}张，"
                f"预设需要{group['size']}张，数量已够，跳过"
            )
            continue

        # 1) 先按卡牌效果找。
        for record in group["records"]:
            for card in cards:
                if not _record_name_hits(record, card):
                    continue
                if not _record_effect_hits(record, card):
                    continue
                if card.get("_has_big_divine") and record.get("reject_divine"):
                    task.log_info(
                        f"预设卡组: 「{_card_name(card)}」效果命中，"
                        f"但这张卡勾了拒绝神闪且当前是神闪形态，跳过"
                    )
                    continue
                task.log_info(
                    f"预设卡组: 选择「{_card_name(card)}」，卡牌效果命中"
                    f"「{(record.get('effects') or [''])[0]}」，"
                    f"牌组当前{actual}/{group['size']}张"
                )
                _bump_name_count(task, _card_name(card))
                return card

        # 2) 效果都不符合，再看神闪效果（只对带大图标的神闪卡）。
        for record in group["records"]:
            if record.get("reject_divine"):
                continue
            for card in cards:
                if not card.get("_has_big_divine"):
                    continue
                if not _record_name_hits(record, card):
                    continue
                if _record_divine_hits(record, _card_description(card)):
                    task.log_info(
                        f"预设卡组: 「{_card_name(card)}」卡牌效果未命中，"
                        f"但神闪效果命中，选择该卡"
                    )
                    _bump_name_count(task, _card_name(card))
                    _add_pending_for_card(task, card)
                    return card

    task.log_info("预设卡组: 预设卡牌都不满足选择条件，按规则回退")
    return _fallback_choice(task, cards)


# ---------------------------------------------------------------------------
# 复制卡牌
# ---------------------------------------------------------------------------

_COPY_PROMPT_KEY = "请选择要复制的卡牌"
_COPY_PAGE_POINT = (0.498, 0.133)


def _name_targets(records):
    """按预设顺序返回唯一卡名、每个卡名的目标张数、同名记录。"""
    order = []
    targets = {}
    records_by_name = {}
    for record in records:
        key = _compact(record.get("name", ""))
        if not key:
            continue
        if key not in targets:
            order.append(record["name"])
            targets[key] = 0
            records_by_name[key] = []
        targets[key] += 1
        records_by_name[key].append(record)
    return order, targets, records_by_name


def _copy_effect_hits(record, card):
    if _record_effect_hits(record, card):
        return True
    description = _compact(_card_description(card))
    if len(description) < 4:
        return False
    return any(
        description in _compact(effect) for effect in record.get("effects") or []
    )


def _read_deck_name_counts(task, names, targets):
    """统计牌组里每个卡名的总张数；打不开或识别不到牌就返回 None。"""
    if not names:
        return {}
    if not _open_deck_page(task):
        task.log_info("预设卡组: 打不开所有牌堆，跳过复制")
        return None
    counts = {name: 0 for name in names}
    all_cards = {}
    previous_signature = None
    unchanged_rounds = 0
    saw_any_card = False
    page = _DECK_PAGE_NAME
    task.sleep(0.6)
    try:
        for step in range(24):
            task.all_texts = _simplify_texts(task.ocr())
            cards = recognize_cards_in_deck(task, page=page)
            reached_next_member = False
            if cards:
                icon_tops = _deck_member_icon_tops(task)
                target_y = _target_member_y(task)
                cards, reached_next_member = _filter_deck_by_member_icon(
                    task, cards, icon_tops, target_y
                )
                if not reached_next_member:
                    levels, target_index = _deck_member_levels(task)
                    cards, reached_next_member = _filter_deck_member_section(
                        task, cards, levels, target_index
                    )
            if cards:
                saw_any_card = True
                for card in cards:
                    key = (
                        _compact(card.get("name", "")),
                        _compact(card.get("description", "")),
                    )
                    all_cards[key] = card
                signature = tuple(
                    sorted(
                        (_compact(card.get("name", "")), _compact(card.get("description", "")))
                        for card in cards
                    )
                )
                for name in names:
                    count = sum(
                        1 for card in cards if _name_matches(name, _card_name(card))
                    )
                    if count > counts[name]:
                        counts[name] = count
                        task.log_info(
                            f"预设卡组: 牌组中「{name}」当前至少{count}张"
                        )
                if signature == previous_signature:
                    unchanged_rounds += 1
                else:
                    unchanged_rounds = 0
                previous_signature = signature
            else:
                unchanged_rounds += 1
            if reached_next_member:
                task.log_info("预设卡组: 已到下一个主战员的牌堆，停止翻页")
                break
            if all(
                counts[name] >= targets.get(_compact(name), 0) for name in names
            ):
                task.log_info("预设卡组: 复制候选数量都已满足，停止翻页")
                break
            if not saw_any_card and step >= 4:
                task.log_warning("预设卡组: 牌组页面连续多屏没有识别到卡牌，结束统计")
                break
            if unchanged_rounds >= 2 and saw_any_card:
                task.log_info("预设卡组: 连续两屏没有新卡牌，判定已到牌组底部")
                break
            if _point_is_white(task, 0.982, 0.925, page):
                task.log_info("预设卡组: 滚动条已到底部")
                break
            _scroll_card_page(task, 0.620, 0.560, -1, page, distance=0.18)
            task.sleep(0.45)
    finally:
        _close_deck_page(task)
    if not saw_any_card:
        task.log_warning("预设卡组: 牌组页面没有识别到卡牌，跳过复制")
        return None
    task._preset_name_counts = counts
    _rebuild_meditation_pending(task, list(all_cards.values()))
    return counts


def _choose_preset_copy_card(task, cards, counts):
    records = load_preset_records(task)
    if not records:
        return None
    order, targets, records_by_name = _name_targets(records)
    for name in order:
        key = _compact(name)
        if counts.get(name, 0) >= targets.get(key, 0):
            continue
        same_name_cards = [
            card for card in cards if _name_matches(name, _card_name(card))
        ]
        if not same_name_cards:
            continue
        # 1) 同名同效果优先，按预设记录从上到下。
        for record in records_by_name.get(key, []):
            for card in same_name_cards:
                if _copy_effect_hits(record, card):
                    task.log_info(
                        f"预设卡组: 复制页选择「{_card_name(card)}」，"
                        f"同名同效果，牌组当前{counts.get(name, 0)}/{targets.get(key, 0)}张"
                    )
                    return card
        # 2) 同名但效果不同，也复制。
        card = same_name_cards[0]
        task.log_info(
            f"预设卡组: 复制页选择「{_card_name(card)}」，"
            f"同名但效果不同，牌组当前{counts.get(name, 0)}/{targets.get(key, 0)}张"
        )
        return card
    return None


def _click_copy_skip(task):
    task.all_texts = _simplify_texts(task.ocr())
    for box in task.all_texts:
        center_x = (box.x + box.width / 2) / task.width
        center_y = (box.y + box.height / 2) / task.height
        if "跳过" in box.name and center_x >= 0.60 and center_y >= 0.85:
            task.log_info("预设卡组: 复制页没有需要复制的卡，点击「跳過」")
            task.click_box(box)
            task.sleep(0.5)
            return True
    task.log_info("预设卡组: 未找到「跳過」，点击固定位置(0.900, 0.930)")
    _move_and_click(task, 0.900, 0.930)
    task.sleep(0.5)
    return True


def handle_preset_copy_card_choice(task: TriggerTask):
    """复制卡牌页面：按预设卡组的同名数量和效果选择。"""
    if not getattr(task, "preset_deck_enabled", False):
        return False
    if not load_preset_records(task):
        return False
    box = find_box_at_point(task, *_COPY_PAGE_POINT)
    prompt = _get_game_text(task, _COPY_PROMPT_KEY)
    if not (box and prompt in box.name):
        return False

    task.log_info("预设卡组: 检测到复制卡牌页面")

    cards = recognize_cards(task, page="复制卡牌选择页面")
    if not cards:
        task.log_warning("预设卡组: 复制页没有识别到卡牌，跳过")
        return _click_copy_skip(task)

    records = load_preset_records(task)
    order, targets, _ = _name_targets(records)
    if not order:
        return False

    # 2. 先识别卡牌是否需要复制：卡名根本不在预设里 → 直接跳过，不打开牌组。
    need_copy = any(
        _name_matches(record.get("name", ""), _card_name(card))
        for record in records
        for card in cards
    )
    if not need_copy:
        task.log_info("预设卡组: 复制页没有预设卡名，直接跳过")
        return _click_copy_skip(task)

    # 3. 需要复制 → 打开所有牌堆统计数量；打不开直接跳过。
    counts = _read_deck_name_counts(task, order, targets)
    if counts is None:
        return _click_copy_skip(task)
    choice = _choose_preset_copy_card(task, cards, counts)
    if choice is None:
        return _click_copy_skip(task)
    _move_and_click(task, choice["x"], choice["y"])
    task.sleep(0.5)
    _bump_name_count(task, _card_name(choice))
    _add_pending_for_card(task, choice)
    _invalidate_deck_cache(task)
    return True


# ---------------------------------------------------------------------------
# 页面入口
# ---------------------------------------------------------------------------

def _has_view_original_button(task):
    """与 handle_view_original 相同的页面判断，避免标题 OCR 慢一拍时被旧逻辑抢先。"""
    original = _get_game_text(task, "查看原件")
    previous = _get_game_text(task, "查看之前的闪光")
    for x, y in ((0.890, 0.051), (0.896, 0.131)):
        box = find_box_at_point(task, x, y)
        if box and (original in box.name or previous in box.name):
            return True
    return False


def handle_preset_deck_flash(task: TriggerTask):
    """灵光一闪 / 神闪选择页面：实验模式下按预设卡组选择。"""
    if not getattr(task, "preset_deck_enabled", False):
        return False
    if not load_preset_records(task):
        return False

    title = _compact(_get_region_text(task, (0.34, 0.10, 0.74, 0.19)))
    if "神之灵光一闪" in title:
        # 4 张卡的神之效果页只作为参考，不参与选卡。
        return False
    is_normal = "请选择灵光一闪效果" in title
    if not is_normal:
        bottom = _compact(_get_region_text(task, (0.28, 0.86, 0.78, 0.98)))
        if "灵光一闪" not in bottom and not _has_view_original_button(task):
            return False

    task._preset_flash_page = "normal" if is_normal else "divine"
    task.log_info(
        "预设卡组: 检测到"
        + ("普通灵光一闪页面" if is_normal else "神闪页面（顶部无标题）")
    )
    result = handle_view_original(
        task,
        card_chooser=_choose_preset_card,
        page_confirmed=True,
    )
    _invalidate_deck_cache(task)
    return result


def _bump_name_count(task, name):
    """选卡/复制/商店买到一张后，同名总数 +1。"""
    counts = getattr(task, "_preset_name_counts", None)
    if not isinstance(counts, dict):
        return
    for key in list(counts):
        if _name_matches(key, name):
            counts[key] = counts.get(key, 0) + 1
            return
    counts[name] = counts.get(name, 0) + 1


def choose_preset_shop_card(task, items, current_credit):
    """商店买卡：预设优先，同名总数未达标，同效果优先，不同效果也买。"""
    records = load_preset_records(task)
    if not records:
        return None
    counts = getattr(task, "_preset_name_counts", None)
    if not isinstance(counts, dict) or not counts:
        return None
    order, targets, records_by_name = _name_targets(records)
    for name in order:
        key = _compact(name)
        if counts.get(name, 0) >= targets.get(key, 0):
            continue
        candidates = [
            item
            for item in items
            if item.get("is_card") and _name_matches(name, item.get("name", ""))
        ]
        if not candidates:
            continue
        affordable = [
            item
            for item in candidates
            if item.get("price") is not None and item["price"] < current_credit
        ]
        if not affordable:
            continue
        for record in records_by_name.get(key, []):
            for item in affordable:
                card = {"name": item.get("name", ""), "description": item.get("text", "")}
                if _record_effect_hits(record, card):
                    _add_pending_for_card(task, card)
                    return item
        item = affordable[0]
        _add_pending_for_card(
            task, {"name": item.get("name", ""), "description": item.get("text", "")}
        )
        return item
    return None


def _invalidate_deck_cache(task):
    task._preset_deck_cache = None
    task._preset_deck_cache_time = 0
