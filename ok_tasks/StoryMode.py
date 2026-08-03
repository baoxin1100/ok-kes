from ok import TriggerTask, og

import utils_story
from utils import _simplify_texts

class StoryMode(TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "半自动剧情模式"
        self.description = "1.剧情内战斗关卡可手动开启出击模式调用自动战斗功能。\n2. 遇到卡厄思关卡请手动打开卡厄思模式。\n3. 剧情战斗关卡队伍需手动配置"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""
        self.trigger_interval = 1
        self.all_texts = []
        # 默认关闭，由用户在界面中手动启停，保持 TriggerTask 自己作为主任务运行
        self.default_config['_enabled'] = False

    def enable(self):
        """开启剧情模式时自动禁用出击和卡厄思模式。"""
        from SortieMode import SortieMode
        from ChaosMode import ChaosMode
        sortie = og.executor.get_task_by_class(SortieMode)
        if sortie and sortie.enabled:
            sortie.disable()
        chaos = og.executor.get_task_by_class(ChaosMode)
        if chaos and chaos.enabled:
            chaos.disable()
        super().enable()

    def run(self):
        # 每帧执行一次 OCR 并转简体, 供各页面处理函数复用
        self.all_texts = _simplify_texts(self.ocr())
        # 依次尝试各页面处理函数, 命中(返回 True)即结束本次循环
        for handle_page in utils_story.PAGE_HANDLERS:
            if handle_page(self):
                return
