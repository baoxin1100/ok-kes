from ok import BaseTask
import re

class GetMengbian(BaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "刷梦边"
        self.description = "梦边"
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""

    def run(self):
        for i in range(300):
            self.log_info("开始第{}次循环".format(i+1))
            self.wait_click_ocr(match="进入", time_out=60, after_sleep=1)
            self.wait_click_ocr(match="进入", time_out=60)
            self.sleep(11)
            if self.ocr(match=re.compile(r".*传说卡牌.*")):
                self.log_info("中立传说卡牌出现")
                self.click(0.758, 0.853)
                self.sleep(1)
                self.click(0.757, 0.953)
                self.sleep(4)
                if self.ocr(match=re.compile(r"梦之边境")):
                    self.log_info("梦之边境已完成，退出循环")
                    break
            self.log_info("未出现中立传说卡牌，继续循环")
            self.click(0.959, 0.049)
            self.wait_click_ocr(match="逃脱", time_out=60)
            self.wait_click_ocr(match="确认",time_out=60,after_sleep=2)


