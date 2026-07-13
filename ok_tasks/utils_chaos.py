from ok import TriggerTask

from utils import (
    _simplify_texts, _get_config_value, _get_card_list, _get_route_priority, _get_game_text,
    find_box_at_point, find_text, find_exact_text,
    _card_has_type_below, select_card, identify_node_type,
    log_credit, handle_battle_crash, handle_close_page,
    handle_center_confirm, handle_settlement, handle_skip,
    handle_destiny_choice, handle_main_member_flash,
    handle_card_reward, handle_equipment,
    handle_select_card, handle_copy_member,
    handle_convert_card,
    handle_negotiation, handle_continue, handle_confirm, handle_enter,
    handle_event_task, handle_route_selection, handle_obtain_reward,
    handle_leave, handle_next_step, handle_select, handle_rest, handle_view_original, handle_weakness_info,
    handle_battle_failed,
    handle_close_button,
    handle_card_assign, handle_non_battle_page, handle_minimizemap, handle_held_cards_page, handle_unknown_page, handle_craft,
    handle_remove, handle_flash, handle_reflash, handle_grant_flash, handle_copy, handle_convert,
    handle_equipment_recast,
    handle_stuck_log,
    is_button_active, _clean_match,
    handle_shop,
)

import re
import random


# ------------------------- 卡厄思模式独有页面处理函数 -------------------------

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


def handle_discovery_select(task: TriggerTask): #忘了按个页面要用
    """发现选择页面: 随机选择一个发现并确认。"""
    title = find_box_at_point(task, 0.498, 0.078)
    # confirm = find_box_at_point(task, 0.880, 0.921)
    # if not (title and title.name == "获得法典" and confirm and confirm.name == "确认"):
    if not (title and title.name == "获得法典"):
        return False

    task.log_info("检测到发现选择页面，随机选择一项")
    positions = [(0.180, 0.519), (0.505, 0.514), (0.818, 0.519)]
    chosen = random.choice(positions)
    task.click(*chosen)
    task.sleep(1)
    # task.click_box(confirm)
    # task.sleep(1)
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
    task.click(0.5, 0.760)
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
        task.click(0.502, 0.943)
        task.sleep(1)
        return True
    return False


# ------------------------- 卡厄思模式独有页面处理函数（续） -------------------------

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


def handle_data_collected(task: TriggerTask):
    """存储数据收集完成页面: 删除存档。"""
    box = find_box_at_point(task, 0.505, 0.111)
    if box and _get_game_text(task, '存储数据收集完成') in box.name:
        if not _get_config_value(task, '保留存档', False):
            task.log_info("保留存档配置为False，删除存档")
            for feature_name in ["deletecards", "deletecards2", "deletecards3"]:
                features = task.find_feature(feature_name=feature_name)
                if features:
                    task.log_info(f"找到{feature_name}特征，点击删除")
                    task.click_box(features[0])
                    task.sleep(1)
                    return True
        task.log_info("检测到存储数据收集完成，由通用按钮处理")
        return True
    return False


# def handle_cares_tip(task: TriggerTask):
#     """卡厄思 TIP 提示页面: 点击关闭。"""
#     box = find_box_at_point(task, 0.502, 0.286)
#     if box and box.name == "TIP":
#         task.click(0.884, 0.915)
#         return True
#     return False


def handle_expedition_unlock(task: TriggerTask):
    """解锁探险记录页面: 点击确定。"""
    box = find_box_at_point(task, 0.5, 0.151)
    if box and _get_game_text(task, '解锁的探险记录') in box.name:
        task.log_info("检测到解锁探险记录页面，点击页面")
        task.click(0.5, 0.95)
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
            task.click(0.706, 0.915)
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
        task.click(0.044, 0.046)
        return True
    task.click(0.420, 0.339)
    task.sleep(0.5)
    travel_ticket = task.ocr(0.933, 0.904, 0.971, 0.943)
    if travel_ticket:
        has_ticket = int(travel_ticket[0].name[0]) > 0
        prefer_gold = _get_config_value(task, '优先使用金币治疗', False)
        if prefer_gold:
            task.log_info("优先使用金币治疗配置为True，点击金币治疗")
            task.click(0.702, 0.924)
        else:
            task.click(0.798 if has_ticket else 0.702, 0.924)
        task.sleep(0.5)
    return True


def handle_treating(task: TriggerTask):
    """治疗进行中页面: 选择治疗方法。"""
    if find_text(task, _get_game_text(task, '选择哪种方法进行治疗')):
        task.log_info("检测到治疗进行中")
        task.click(0.765, 0.500)
        return True
    return False


def handle_treat_approve(task: TriggerTask):
    """治疗完成页面: 点击批准。"""
    if find_text(task, _get_game_text(task, '点击批准')):
        task.log_info("检测到治疗完成，点击批准")
        task.click(0.768, 0.810)
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


# 卡厄思模式 PAGE_HANDLERS
PAGE_HANDLERS = [
    log_credit,
    handle_stuck_log, #画面卡住检测，仅输出日志

    handle_equipment, #装备选择
    handle_card_assign,
    handle_confirm, #确认按钮
    handle_convert, #转换按钮
    handle_shop, #德朗商店
    handle_rest, #休息/商店入口
    handle_close_button, #关闭按钮
    handle_remove, #移除按钮
    handle_flash, #闪光按钮
    handle_reflash, #重新闪光按钮
    handle_grant_flash, #赋予闪光按钮
    handle_copy, #复制按钮
    handle_leave, #离开按钮
    handle_mental_breakdown, #精神崩溃，优先级高于下一步按钮
    handle_data_collected, #存储数据收集完成，优先级高于下一步按钮
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
    handle_close_page,
    handle_center_confirm,
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_card_reward,
    handle_mask_card,
    handle_select_card,
    handle_copy_member,
    handle_convert_card,
    handle_discovery_select,
    handle_negotiation,
    handle_continue,
    handle_enter,
    handle_route_selection,
    handle_obtain_reward,
    handle_view_original,
    handle_battle_failed,
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
    handle_skip,
    handle_event_task,
    handle_held_cards_page,
    handle_unknown_page,
]
