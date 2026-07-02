from ok import TriggerTask

from utils import (
    _simplify_texts, _get_config_value, _get_card_list, _get_route_priority,
    find_box_at_point, find_text, find_exact_text,
    _card_has_type_below, handle_copy, handle_flash, handle_reflash, handle_grant_flash, handle_remove, select_card, identify_node_type,
    log_credit, handle_battle_crash, handle_close_page,
    handle_center_confirm, handle_settlement, handle_skip,
    handle_destiny_choice, handle_main_member_flash,
    handle_card_reward, handle_equipment, handle_mask_card,
    handle_remove_card, handle_copy_member, handle_copy_card,
    handle_flash_card, handle_copy_card_pick, handle_convert_card,
    handle_negotiation, handle_continue, handle_confirm, handle_enter,
    handle_event_task, handle_route_selection, handle_obtain_reward,
    handle_leave, handle_select, handle_rest, handle_view_original, handle_weakness_info,
    handle_battle_failed, handle_data_collected, handle_mental_breakdown,
    handle_trauma_center, handle_explore_result, handle_treating,
    handle_treat_approve, handle_cares_tip, handle_close_button,
    handle_expedition_unlock, handle_card_assign, handle_non_battle_page, handle_minimizemap, handle_held_cards_page,
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


def handle_memory_elimination(task: TriggerTask):
    """记忆消除页面: 点击记忆消除按钮。"""
    box = find_box_at_point(task, 0.589, 0.703)
    if box and box.name == "记忆消除":
        task.log_info("检测到记忆消除页面，点击记忆消除")
        task.click_box(box)
        task.sleep(0.5)
        return True
    return False


# 卡厄思模式 PAGE_HANDLERS
PAGE_HANDLERS = [
    log_credit,

    handle_rest,
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
    handle_zero_system_home,
    handle_codex_search,
    handle_explore_result,
    handle_expedition_unlock,
    handle_cares_tip,
    handle_memory_elimination,
    handle_skip,
    handle_event_task,
    handle_held_cards_page,
]