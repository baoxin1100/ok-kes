from ok import TriggerTask, og

import utils_sortie
from opencc import OpenCC
from config_io import make_export_callback, make_import_callback

_cc = OpenCC('t2s')  # 繁转简，用于OCR文本统一转换


class SortieMode(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动出击模式"
        self.description = "1. 自动战斗依赖按键识别，请在游戏设置中打开快捷键显示，提升出牌准确率。\n2. 国际服玩家请到软件左下角设置页内将\"游戏语言\"设置为繁体中文。"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""
        self.trigger_interval = 1
        self.all_texts = []
        self.default_config["_enabled"] = False
        self.default_config["路线优先级"] = ["休息", "事件", "小怪", "boss"]
        self.default_config["主战员优先级"] = ["米卡", "尼娅", "蒂菲拉", "麦格纳", "卡修斯"]
        self.default_config["出战主战员优先级"] = ["海德玛丽", "九", "力", "绯"]
        self.default_config["获得卡牌优先级"] = ["展开极光", "剑雨", "一缕光芒","缕光芒","凝聚极光"]
        self.default_config["移除卡牌列表"] = ["剑幕"]
        self.default_config["复制卡牌列表"] = ["剑雨", "展开极光", "一缕光芒","缕光芒"]
        self.default_config["闪光卡牌列表"] = ["剑雨", "展开极光", "一缕光芒","缕光芒"]
        self.default_config["领取奖励"] = False
        self.default_config["出牌优先级"] = ["剑雨", "水之源", "一缕光芒", "万众英雄","极光剑", "展开极光","解放极光"]
        self.default_config["丢弃卡牌优先级"] = ["展开极光", "极光剑", "凝聚极光"]
        self.default_config["进入商店"] = False
        self.default_config["卡牌奖励优先级"] = ["梦之边境", "装备包"]
        self.default_config["任务优先级"] = ["选取随机3条命运","信用点增加", "移除"]
        self.default_config["拉黑主战员"] = ["黛安娜", "阿黛尔海特"]
        self.default_config["跳过非优先级卡牌"] = True
        self.default_config["优先移除基础牌"] = True
        self.default_config["生命值大于多少优先闪光(百分比)"] = "60"
        self.default_config["只打第一层"] = True
        # self.default_config["从右往左出牌"] = True
        self.node_status = {"shop": False, "flash_or_rest": False, "reach_final_boss": False, "final_boss_battle": False, "pass_final_boss_count": 0, "total_rounds": 0, "success_rounds": 0}

        self.config_type = {
            'export_config': {'type': 'button', 'text': '导出配置', 'callback': make_export_callback(self)},
            'import_config': {'type': 'button', 'text': '导入配置', 'callback': make_import_callback(self)},
        }

    def enable(self):
        """开启出击模式时自动禁用卡厄思模式。"""
        from ChaosMode import ChaosMode
        chaos = og.executor.get_task_by_class(ChaosMode)
        if chaos and chaos.enabled:
            chaos.disable()
        super().enable()

    def _ocr_and_simplify(self):
        """执行OCR并将所有识别文本转简体。"""
        texts = self.ocr()
        for b in texts:
            b.name = _cc.convert(b.name)
        return texts

    def run(self):
        self.all_texts = self._ocr_and_simplify()
        for handle_page in utils_sortie.PAGE_HANDLERS:
            if handle_page(self):
                return