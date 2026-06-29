from ok import TriggerTask

import utils_sortie


class SortieMode(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动出击模式"
        self.description = "自动出击模式"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""
        self.trigger_interval = 1
        self.all_texts = []
        self.default_config["_enabled"] = False
        self.default_config["路线优先级"] = ["休息", "事件", "小怪", "boss"]
        self.default_config["主战员优先级"] = ["尼娅", "麦格纳", "米卡", "卡修斯"]
        self.default_config["出战主战员优先级"] = ["海德玛丽", "九", "力", "绯"]
        self.default_config["获得卡牌优先级"] = ["展开极光", "剑雨", "一缕光芒","缕光芒","凝聚极光"]
        self.default_config["移除卡牌列表"] = ["剑幕"]
        self.default_config["复制卡牌列表"] = ["剑雨", "展开极光", "一缕光芒","缕光芒"]
        self.default_config["闪光卡牌列表"] = ["剑雨", "展开极光", "一缕光芒","缕光芒"]
        self.default_config["领取奖励"] = False
        self.default_config["使用体力药"] = False
        self.default_config["出牌优先级"] = ["剑雨", "一缕光芒","缕光芒", "极光剑", "展开极光"]
        self.default_config["丢弃卡牌优先级"] = ["展开极光", "极光剑", "凝聚极光"]
        self.default_config["进入商店"] = False
        self.default_config["卡牌奖励优先级"] = ["梦之边境", "装备包"]
        self.default_config["任务优先级"] = ["选取随机3条命运","信用点增加", "移除"]

    def run(self):
        self.all_texts = self.ocr()
        for handle_page in utils_sortie.PAGE_HANDLERS:
            if handle_page(self):
                return