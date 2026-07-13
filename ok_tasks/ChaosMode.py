from ok import TriggerTask, og

import utils_chaos
from opencc import OpenCC

_cc = OpenCC('t2s')  # 繁转简，用于OCR文本统一转换

class ChaosMode(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动卡厄思模式"
        self.description = "1. 请主动打开游戏内自动战斗和自动剧情功能。\n2. 国际服玩家请到软件左下角设置页内将\"游戏语言\"设置为繁体中文。"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""
        self.trigger_interval = 1
        self.all_texts = []
        # 默认关闭，由用户在界面中手动启停，保持 TriggerTask 自己作为主任务运行
        self.default_config['_enabled'] = False
        # 事件任务优先级列表, 匹配到包含对应文字的选项时会优先选择
        self.default_config['任务优先级'] = ["复制","信用点增加", "移除"]
        # 闪光卡牌优先级配置 (JSON字符串): {"卡牌名": ["效果关键词1", "效果关键词2"], ...}
        self.default_config['闪光优先级'] = '{"剑雨": ["生成2张极光剑", "生成1张极光剑"]}'
        # 卡牌策略配置 (列表)
        self.default_config['移除卡牌列表'] = ["剑幕", "剑光", "水之伞", "海潮的庇护", "作战分析"]
        self.default_config['闪光卡牌列表'] = ["展开极光", "剑雨", "缕光芒", "一缕光芒", "万众英雄"]
        self.default_config['复制卡牌列表'] = ["展开极光", "剑雨", "缕光芒", "一缕光芒", "万众英雄"]
        # 路线节点优先级 (列表), 越靠前优先级越高
        self.default_config['优先使用金币治疗'] = True
        self.default_config['治疗崩溃'] = True
        self.default_config['进入商店'] = False
        self.default_config['保留存档'] = False
        self.default_config['路线优先级'] = ["休息", "事件", "小怪", "boss"]
        self.node_status = {"shop": False, "flash_or_rest": False}

    def enable(self):
        """开启卡厄思模式时自动禁用出击模式。"""
        from SortieMode import SortieMode
        sortie = og.executor.get_task_by_class(SortieMode)
        if sortie and sortie.enabled:
            sortie.disable()
        super().enable()

    def _ocr_and_simplify(self):
        """执行OCR并将所有识别文本转简体。"""
        texts = self.ocr()
        for b in texts:
            b.name = _cc.convert(b.name)
        return texts

    def run(self):
        # 每帧执行一次 OCR 并转简体, 供各页面处理函数复用
        self.all_texts = self._ocr_and_simplify()
        # 依次尝试各页面处理函数, 命中(返回 True)即结束本次循环
        for handle_page in utils_chaos.PAGE_HANDLERS:
            if handle_page(self):
                return