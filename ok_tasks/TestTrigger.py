from ok import TriggerTask

from utils import recognize_cards_in_deck


class TestTrigger(TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试trigger"
        self.description = "测试trigger"
        self.trigger_interval = 2
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""

    def run(self):
        self.all_texts = self.ocr()
        cards = recognize_cards_in_deck(self, page="测试trigger")
        selected_cards = [card for card in cards if card["selected"]]
        for card in selected_cards:
            self.log_info(
                f"测试trigger: 当前选中卡牌名称=「{card['name']}」，"
                f"类型=「{card['type']}」，描述=「{card['description']}」"
            )
