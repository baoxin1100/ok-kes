from ok import TriggerTask

from utils import (
    handle_confirm,
    handle_enter,
    handle_close_page,
    handle_next_step,
    find_box_at_point,
)
from utils_chaos import handle_battle_auto_check


# ------------------------- 页面处理函数 -------------------------

def handle_auto_chat(task: TriggerTask):
    """自动对话检查: autochatenable置信度低于0.96时点击开启。"""
    search_box = task.box_of_screen(0.655, 0.007, 0.996, 0.097)
    auto_chat = task.find_one(feature_name="autochatenable", box=search_box)
    if auto_chat and auto_chat.confidence < 0.96:
        task.log_info(f"自动对话未开启，当前匹配置信度: {auto_chat.confidence:.2%}，点击开启")
        task.click_box(auto_chat)
        return True
    return False


def handle_view_event(task: TriggerTask):
    """查看事件页面: 在指定区域检测check特征并点击。"""
    search_box = task.box_of_screen(0.084, 0.125, 0.995, 0.875)
    check_box = task.find_one(feature_name="check", box=search_box)
    if check_box:
        task.log_info("检测到查看事件，点击check特征")
        task.click_box(check_box)
        task.sleep(0.5)
        return True
    return False


# def handle_team_config(task: TriggerTask):
#     """队伍配置页面: 检测(0.122,0.047)处'配置队伍'文本，选择空槽位补充角色。"""
#     title_box = find_box_at_point(task, 0.122, 0.047)
#     if not (title_box and "配置队伍" in title_box.name):
#         return False
#     task.log_info("检测到队伍配置页面")
#     slots = [
#         (0.057, 0.611, 0.132, 0.456),
#         (0.270, 0.610, 0.344, 0.444),
#         (0.484, 0.608, 0.554, 0.436),
#     ]
#     for check_x, check_y, click_x, click_y in slots:
#         box = find_box_at_point(task, check_x, check_y)
#         if box is None or not box.name.strip():
#             task.log_info(f"槽位({check_x},{check_y})为空，点击({click_x},{click_y})补充角色")
#             task.click(click_x, click_y)
#             task.sleep(2)
#             return True
#     task.log_info("所有槽位已有角色，无需补充")
#     return False


def handle_enter_stage(task: TriggerTask):
    """入场按钮: 检测(0.820,0.931)位置的入场按钮并点击。"""
    box = find_box_at_point(task, 0.820, 0.931)
    if box and "入场" in box.name:
        task.log_info("检测到入场按钮，点击入场")
        task.click_box(box)
        task.sleep(1)
        return True
    return False


def handle_enter_story_or_battle(task: TriggerTask):
    """故事/战斗入口页面: 点击最左侧的enterstory或enterbattle特征。"""
    search_box = task.box_of_screen(0.085, 0.124, 0.995, 0.874)
    story_boxes = task.find_feature(feature_name="enterstory", box=search_box)
    battle_boxes = task.find_feature(feature_name="enterbattle", box=search_box, threshold=0.85)
    candidates = [
        *((box, "故事") for box in story_boxes),
        *((box, "战斗") for box in battle_boxes),
    ]
    if candidates:
        chosen_box, entrance_type = min(candidates, key=lambda item: item[0].x)
        task.log_info(
            f"检测到{entrance_type}入口，点击最左侧特征"
            f"（x={chosen_box.x}, confidence={chosen_box.confidence:.2f}）"
        )
        task.click_box(chosen_box)
        task.sleep(2)
        return True
    return False


def handle_skip_story(task: TriggerTask):
    """可跳过剧情页面: 检测到skipstory特征则点击跳过。"""
    boxes = task.find_feature(feature_name="skipstory")
    if boxes:
        task.log_info("检测到可跳过剧情页面，点击跳过")
        task.click_box(boxes[0])
        task.sleep(1)
        return True
    return False


def handle_observe(task: TriggerTask):
    """观测卡厄思关卡页面: 在区域内检测文本'观测'并点击。"""
    x1, y1, x2, y2 = 0.092, 0.214, 0.962, 0.792
    for b in task.all_texts:
        cx = (b.x + b.width / 2) / task.width
        cy = (b.y + b.height / 2) / task.height
        if x1 <= cx <= x2 and y1 <= cy <= y2 and b.name.strip() == "观测":
            task.log_info("检测到观测卡厄思关卡，点击观测")
            task.click_box(b)
            task.sleep(4)
            return True
    return False


# 剧情模式页面处理函数列表（按优先级排序）
PAGE_HANDLERS = [
    # handle_team_config,  #队伍配置（最高优先级）
    handle_skip_story,  #跳过剧情（最高优先级）
    handle_auto_chat,  #自动对话检查
    handle_view_event,  #查看事件
    handle_confirm,  #确认按钮
    handle_enter,  #进入按钮
    handle_enter_stage,  #入场按钮
    handle_close_page,  #点击屏幕关闭页面
    handle_enter_story_or_battle,
    handle_observe,  #观测卡厄思关卡
    handle_next_step,
    handle_battle_auto_check,  #自动战斗检测
]
