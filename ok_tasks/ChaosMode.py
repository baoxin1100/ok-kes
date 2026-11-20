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
        self.default_config['关键词暂停'] = ""
        self.config_description['关键词暂停'] = "多个关键词可用中英文逗号或分号（,，;；）分隔；OCR结果包含任意一个关键词时暂停工具，等待手动接管；留空不启用。"
        self.default_config['刷存档主战员'] = "海德玛丽"
        self.default_config['存储数据保存上限大于多少'] = 120
        self.default_config['保留大于多少TB的存档'] = 62000
        self.default_config['领取奖励(只使用验证卡)'] = False
        # 事件任务优先级列表, 匹配到包含对应文字的选项时会优先选择
        self.default_config['任务优先级'] = ["复制","信用点增加", "移除"]
        self.default_config['拉黑任务'] = ["咒术卡牌", "压力"]
        self.default_config['命运优先级'] = []
        self.default_config['拉黑命运'] = []
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
        self.default_config['商店刷新信用点阈值'] = 300
        self.default_config['装备1号位优先级'] = ["蚀化臂铠"]
        self.default_config['装备2号位优先级'] = ["拷问工具箱"]
        self.default_config['装备3号位优先级'] = ["异象石碑"]
        self.default_config['刻印刷取'] = False
        self.default_config['首层未刷到刻印重开'] = False
        self.default_config['最终战前已命中词条至少为多少'] = 0
        self.default_config['刻印优先级'] = []
        self.default_config['卡牌奖励优先级'] = ["梦之边境"]
        self.default_config['指定记忆卡牌'] = ""
        self.default_config['加工记忆'] = False
        self.default_config['加工记忆词条'] = ""
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
                            "precision_memory_visited": False,
                            "removed_card_count": 0,
                            "neutral_card_count": 0}
        self.member_status = {
            "equipment": {
                "names": ["", "", ""],
                "descriptions": ["", "", ""],
                "qualities": ["", "", ""],
                "engravings": [
                    {"type": "", "text": "", "rank": None},
                    {"type": "", "text": "", "rank": None},
                    {"type": "", "text": "", "rank": None},
                ],
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
            '存储数据保存上限大于多少': {'min': 0, 'max': 300},
            '最终战前已命中词条至少为多少': {'min': 0, 'max': 3},
        }
        self.config_description['游戏语言'] = "国际服请设置为繁体中文"
        self.config_description['存储数据保存上限大于多少'] = (
            "赛季卡厄思（再次观测）与零式系统（重新合成）的目标pt上限（如填150则刷到>=150pt才进入）；赛季货币不足时会自动停止刷新并直接进入。"
        )
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
        self.config_description['商店刷新信用点阈值'] = (
            "德朗商店免费刷新次数用完后，仅当信用点大于该值且足够支付刷新价格时才付费刷新。"
        )
        self.config_description['加工记忆'] = (
            "开启后，在记忆雕琢界面若当前记忆卡牌未命中“加工记忆词条”，会先点击左侧“记忆加工”转换词条，再点击右侧“记忆雕琢”强化。"
        )
        self.config_description['加工记忆词条'] = (
            "开启“加工记忆”时生效：填写目标记忆卡牌词条关键字（多个候选词条可用逗号分隔），无需完整填写，字序与游戏原文一致即可。"
        )
        self.config_description['刻印刷取'] = (
            "开启后，在事件/战斗/商店获得装备时自动识别光明/黑暗刻印并按“刻印优先级”刷取与替换；开启后词条优先级高于装备优先级。"
        )
        self.config_description['首层未刷到刻印重开'] = (
            "需同时开启“刻印刷取”才生效：第一层通关后若目标主战员未获得命中“刻印优先级”的刻印，则自动退出重刷。"
        )
        self.config_description['最终战前已命中词条至少为多少'] = (
            "需同时开启“刻印刷取”才生效：第2层最终Boss前（最后一个休息点全部操作完成后）若刷存档主战员持有的已命中刻印词条数量小于该值（0~3，0为不限制），则退出并删档重来。"
        )
        self.config_description['刻印优先级'] = (
            "开启“刻印刷取”时生效：按列表顺序填写目标刻印词条关键字（无需完整填写，字序与游戏原文一致即可），越靠前优先级越高。"
        )
        self.config_description['命运优先级'] = (
            "命运选择界面按列表顺序优先选择名称或效果描述命中关键字的命运（无需完整填写，字序与游戏原文一致即可）。"
        )
        self.config_description['拉黑命运'] = (
            "命运选择界面避开名称或效果描述命中关键字的命运（如“领导力”“中立”等）；若三个命运均被拉黑则自动跳过。"
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
