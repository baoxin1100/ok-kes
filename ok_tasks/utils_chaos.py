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
    handle_escape,
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

    # 如果已到达最终boss节点，标记boss战状态
    if hasattr(task, 'node_status') and task.node_status.get('reach_final_boss', False):
        task.node_status['final_boss_battle'] = True
        task.log_info("检测到最终boss战斗开始，final_boss_battle=True")
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
    if replace_box and "替换" in replace_box.name:
        task.log_info("检测到替换模式（A逻辑）")

        # ===== A逻辑：刻印1 =====
        task.log_info("点击刻印1")
        task.click(0.399, 0.472)
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
                        task.click(0.916, 0.810)
                        task.sleep(1)
                        return True
            # 无法刷新，点击跳过
            task.log_info("无法刷新，点击跳过")
            task.click(0.747, 0.932)
            task.sleep(1)
            return True

        # ===== 刻印1命中，继续刻印2 =====
        task.log_info("刻印1命中，点击刻印2")
        task.click(0.399, 0.610)
        task.sleep(0.5)

        slot2_desc = _get_region_text(task, slot_desc_region)
        task.log_info(f"刻印2描述: {slot2_desc}")

        if specify_text in slot2_desc:
            # 刻印2也命中，点击跳过
            task.log_info("刻印2也命中配置，点击跳过")
            task.click(0.747, 0.932)
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
                    task.click(0.916, 0.810)
                    task.sleep(1)
                    return True

        # 无法刷新，点击跳过
        task.log_info("无法刷新，点击跳过")
        task.click(0.747, 0.932)
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
                task.click(0.913, 0.667)
                task.sleep(1)
                return True

    task.log_info("无可刷新次数，跳过")
    return False


def handle_mask_card(task: TriggerTask):
    """面具获得卡牌页面: 检测到0.507,0.090处有"面具"，则为面具卡牌获得页面。
    检测0.120,0.228,0.945,0.418范围内是否有三个"人格面具"文本，
    如果不足三个则说明已选择过人格面具，点击跳过。
    否则提取三张卡牌描述区域文本，匹配配置中"指定面具卡牌"内容。
    匹配成功则点击对应卡牌，否则刷新或跳过。"""
    box = find_box_at_point(task, 0.507, 0.090)
    if not (box and "面具" in box.name and "获得卡牌" in box.name):
        return False

    task.log_info("检测到面具卡牌获得页面")

    # 检测0.120,0.228,0.945,0.418范围内是否有人格面具文本（三个）
    person_mask_boxes = [
        b for b in task.all_texts
        if 0.120 <= (b.x + b.width / 2) / task.width <= 0.945
        and 0.228 <= (b.y + b.height / 2) / task.height <= 0.418
        and "人格面具" in b.name
    ]
    if len(person_mask_boxes) < 3:
        task.log_info("已选择过人格面具，点击跳过")
        skip_box = find_text(task, r'跳过')
        if skip_box:
            task.click_box(skip_box)
            task.sleep(0.5)
            # task.click(0.654, 0.626)
        return True

    task.log_info("检测到3张人格面具，提取卡牌描述")

    # 三张卡牌描述区域（暂只启用第一张）
    desc_regions = [
        (0.141, 0.586, 0.325, 0.779),
        # (0.427, 0.606, 0.615, 0.782),
        # (0.716, 0.547, 0.902, 0.779),
    ]

    specify_text = _get_config_value(task, '指定面具卡牌', "丢弃最多2张卡牌")
    for i, (rx1, ry1, rx2, ry2) in enumerate(desc_regions):
        desc_texts = [
            b.name.strip() for b in task.all_texts
            if rx1 <= (b.x + b.width / 2) / task.width <= rx2
            and ry1 <= (b.y + b.height / 2) / task.height <= ry2
            and b.name.strip()
        ]
        desc_text = "".join(desc_texts)
        task.log_info(f"卡牌{i+1}描述: {desc_text}")
        if specify_text in desc_text:
            task.log_info(f"卡牌{i+1}描述包含「{specify_text}」，点击该卡牌")
            click_x = (rx1 + rx2) / 2
            click_y = (ry1 + ry2) / 2
            task.click(click_x, click_y)
            task.sleep(0.5)
            return True

    # 未匹配到指定卡牌，检查剩余刷新次数
    refresh_box = find_box_at_point(task, 0.313, 0.931)
    if refresh_box:
        match = re.search(r'(\d+)/3', refresh_box.name)
        if match:
            remaining = int(match.group(1))
            task.log_info(f"未匹配到指定面具卡牌，剩余刷新次数: {remaining}")
            if remaining > 0:
                task.log_info(f"剩余刷新次数{remaining}>0，点击刷新")
                task.click(0.313, 0.931)
                task.sleep(1)
                return True

    task.log_info("无刷新次数或无需刷新，点击跳过")
    skip_box = find_text(task, r'跳过')
    if skip_box:
        task.click_box(skip_box)
        task.sleep(0.5)
        # task.click(0.654, 0.626)
    return True


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
        return False
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


def handle_chaos_reward_claim(task: TriggerTask):
    """卡厄思模式奖励领取页面: 如果0.568,0.711处文本包含"获得"，则为奖励领取页面。
    识别0.959,0.281处"\d/\d"作为当前/最大战利品验证卡，
    如果验证卡大于0则点击获得，否则重置"领取奖励(只使用验证卡)"为False并取消。"""
    claim_box = find_box_at_point(task, 0.568, 0.711)
    if not (claim_box and "获得" in claim_box.name):
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
            task.click(0.352, 0.708)
            task.sleep(1)
            return True
    else:
        task.log_info("未检测到战利品验证卡信息，点击取消")
        task.click(0.352, 0.708)
        task.sleep(1)
        return True


def handle_chaos_reward_settlement(task: TriggerTask):
    """卡厄思奖励结算页面: 如果0.552,0.067处包含"结算"，则为卡厄思奖励结算页面。
    如果0.851,0.389处包含"获得"且当前战利品验证卡>0，则点击获得按钮。"""
    title_box = find_box_at_point(task, 0.552, 0.067)
    if not (title_box and "结算" in title_box.name):
        return False

    task.log_info("检测到卡厄思奖励结算页面")

    if not _get_config_value(task, '领取奖励(只使用验证卡)', False):
        task.log_info("领取奖励(只使用验证卡)配置为False，跳过")
        return False

    # 检查0.851,0.389处是否有"获得"按钮
    reward_box = find_box_at_point(task, 0.851, 0.389)
    if not (reward_box and "获得" in reward_box.name):
        task.log_info("未检测到获得按钮，跳过")
        return False

    task.log_info("检测到获得按钮，点击获得")
    task.click_box(reward_box)
    task.sleep(1)
    return True


# 卡厄思模式 PAGE_HANDLERS
PAGE_HANDLERS = [
    log_credit,
    handle_stuck_log, #画面卡住检测，仅输出日志

    handle_center_confirm, #页面中央确认按钮
    handle_chaos_mask_engraving, #面具卡牌刻印获取页面
    handle_equipment, #装备选择
    handle_card_assign,
    handle_confirm, #确认按钮
    handle_mask_card, #面具卡牌获得页面
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
    handle_battle_failed, #战斗失败，优先级高于下一步
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
    handle_settlement,
    handle_destiny_choice,
    handle_main_member_flash,
    handle_card_reward,
    handle_select_card,
    handle_copy_member,
    handle_convert_card,
    handle_discovery_select,
    handle_negotiation,
    handle_chaos_reward_settlement, #卡厄思奖励结算页面，优先级高于继续按钮
    handle_chaos_reward_claim, #卡厄思模式奖励领取页面
    handle_continue,
    handle_enter,
    handle_route_selection,
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
    handle_skip,
    handle_event_task,
    handle_held_cards_page,
    handle_escape,
    handle_unknown_page,
]
