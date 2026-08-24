from ok import TriggerTask, og

import utils_chaos
from config_io import (
    make_export_callback,
    make_import_callback,
    make_save_local_config_callback,
    make_switch_local_config_callback,
    migrate_flash_priority_config_file,
    migrate_game_language_config_file,
)
from config_sync import check_upload_if_needed, show_hot_configs_dialog
from utils import (
    reset_all_status,
    _migrate_route_boss_to_elite,
    _simplify_texts,
)

class ChaosMode(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动卡厄思模式"
        self.description = "1. 请主动打开游戏内自动战斗和自动剧情功能。\n2. 国际服玩家请将本模式配置中的\"游戏语言\"设置为繁体中文。"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""
        self.trigger_interval = 1
        self.all_texts = []
        # 默认关闭，由用户在界面中手动启停，保持 TriggerTask 自己作为主任务运行
        self.default_config['_enabled'] = False
        self.default_config['配置操作'] = ""
        self.default_config['游戏语言'] = "简体中文"
        self.default_config['刷存档主战员'] = "海德玛丽"
        self.default_config['存储数据价值大于等于多少层级'] = 12
        self.default_config['保留大于多少TB的存档'] = 62000
        self.default_config['领取奖励(只使用验证卡)'] = False
        # 事件任务优先级列表, 匹配到包含对应文字的选项时会优先选择
        self.default_config['任务优先级'] = ["复制","信用点增加", "移除"]
        self.default_config['拉黑任务'] = ["咒术卡牌", "压力"]
        # 闪光卡牌优先级配置，按列表顺序匹配卡牌名称与描述的组合文本
        self.default_config['闪光优先级'] = [
            "剑雨感应：生成2张极光剑",
            "剑雨赋予其回收",
            "缕光芒80%",
            "缕光芒216%",
            "展开极光70%",
            "展开极光安息唯一",
            "展开极光200%",
        ]
        # 卡牌策略配置 (列表)
        self.default_config['移除卡牌列表'] = ["剑幕", "剑光", "水之伞", "海潮的庇护", "作战分析"]
        self.default_config['闪光卡牌列表'] = ["展开极光", "剑雨", "缕光芒", "一缕光芒", "万众英雄"]
        self.default_config['复制卡牌列表'] = ["展开极光", "剑雨", "缕光芒", "一缕光芒", "万众英雄"]
        self.default_config['需要冥想的卡牌'] = ["剑雨", "展开极光"]
        self.default_config['多少信用点以上冥想'] = 300
        self.default_config['装备1号位优先级'] = ["蚀化臂铠"]
        self.default_config['装备2号位优先级'] = ["拷问工具箱"]
        self.default_config['装备3号位优先级'] = ["异象石碑"]
        self.default_config['卡牌奖励优先级'] = ["梦之边境"]
        self.default_config['首层刷特定闪光'] = False
        self.default_config['刷空档'] = False
        self.default_config['优先使用金币治疗'] = True
        self.default_config['治疗崩溃'] = True
        self.default_config['优先移除基础牌'] = True
        self.default_config['进入商店'] = False
        self.default_config['指定面具卡牌'] = "丢弃最多2张卡牌"
        self.default_config['面具卡牌刻印'] = "自身攻击卡牌伤害总量提升30%"
        self.default_config['刷初始卡牌'] = ""
        self.default_config['只打第一层'] = False
        # 路线节点优先级 (列表), 越靠前优先级越高
        self.default_config['路线优先级'] = ["休息", "事件", "小怪", "精英"]
        self.default_config['几轮后停止(0为不停止)'] = 0
        self.default_config['第几层boss前自动暂停'] = "不暂停"
        self.node_status = {"shop": False, "flash_or_rest": False, "reach_final_boss": False, "final_boss_battle": False, "pass_final_boss_count": 0, 
                            "total_rounds": 0, "success_rounds": 0, "node_count": 0, "enter_new_node": False, "node_type": "",
                            "is_escaped": False, "save_target_member": False,
                            "target_mask_card_position": -1,
                            "get_specific_flash": False,
                            "removed_card_count": 0,
                            "neutral_card_count": 0}
        self.member_status = {
            "equipment": {
                "names": ["", "", ""],
                "descriptions": ["", "", ""],
                "qualities": ["", "", ""],
            },
            "deck": {},
        }

        self._last_upload_time = 0
        self.config_type = {
            '游戏语言': {'type': 'drop_down', 'options': ['简体中文', '繁体中文']},
            '配置操作': {
                'type': 'button',
                'buttons': [
                    {'text': '导入配置码', 'callback': make_import_callback(self)},
                    {'text': '导出配置码', 'callback': make_export_callback(self)},
                    {'text': '热门配置', 'callback': self._show_hot_configs},
                    {'text': '保存配置', 'callback': make_save_local_config_callback(self, 'chaos')},
                    {'text': '切换配置', 'callback': make_switch_local_config_callback(self, 'chaos')},
                ],
            },
            '第几层boss前自动暂停': {'type': 'drop_down', 'options': ['不暂停', '1', '2']},
            '存储数据价值大于等于多少层级': {'min': 0, 'max': 15},
        }
        self.config_description['游戏语言'] = "国际服请设置为繁体中文"
        self.config_description['闪光优先级'] = (
            "卡牌名称和描述无需完整填写，输入几个关键字即可，但顺序须与游戏原文一致。"
        )
        self.config_description['刷初始卡牌'] = (
            "填写目标卡牌名称后反复刷新初始卡牌；不能与“刷空档”同时使用。"
        )
        self.config_description['刷空档'] = (
            "初始任务必须包含“移除2张”，否则重新开始；不能与“刷初始卡牌”同时使用。"
        )
        self.config_description['首层刷特定闪光'] = (
            "默认刷闪光优先级第一张，可刷神闪，第一层没刷出自动逃脱"
        )

    def load_config(self):
        migrate_flash_priority_config_file(self)
        migrate_game_language_config_file(self)
        super().load_config()

    def enable(self):
        """开启卡厄思模式时自动禁用出击模式，重置状态并迁移配置。"""
        from SortieMode import SortieMode
        sortie = og.executor.get_task_by_class(SortieMode)
        if sortie and sortie.enabled:
            sortie.disable()
        reset_all_status(self)
        _migrate_route_boss_to_elite(self)
        super().enable()

    def _check_upload_if_needed(self):
        check_upload_if_needed(self, "chaos")

    def _show_hot_configs(self):
        show_hot_configs_dialog(self, "chaos")

    def run(self):
        # 每帧执行一次 OCR 并转简体, 供各页面处理函数复用
        self.all_texts = _simplify_texts(self.ocr())
        # 依次尝试各页面处理函数, 命中(返回 True)即结束本次循环
        for handle_page in utils_chaos.PAGE_HANDLERS:
            if handle_page(self):
                return
        # 帧末尾检查是否需要上传配置
        self._check_upload_if_needed()
