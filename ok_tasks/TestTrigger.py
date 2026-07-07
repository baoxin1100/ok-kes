from ok import TriggerTask
import re

_hand_card_region = (0.159, 0.683, 0.836, 0.831)

def _card_key(text):
    table = str.maketrans("①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺❻❼❽❾❿⓵⓶⓷⓸⓹⓺⓻⓼⓽⓾０１２３４５６７８９",
                         "1234567890123456789012345678900123456789")
    text = text.translate(table)
    m = re.search(r"\d", text)
    return m.group(0) if m else None


def _read_hand_count(boxes, width, height):
    """从OCR结果中读取底部手牌数 x/10"""
    for b in boxes:
        cx = (b.x + b.width / 2) / width
        cy = (b.y + b.height / 2) / height
        if 0.45 <= cx <= 0.55 and 0.96 <= cy <= 0.99:
            match = re.search(r"(\d+)/10", b.name)
            if match:
                return int(match.group(1))
    return None


class TestTrigger(TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试trigger"
        self.description = "测试trigger"
        self.trigger_interval = 2
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""

    def run(self):
        all_texts = self.ocr()

        # === 测试：优化后的手牌识别 ===
        x1, y1, x2, y2 = _hand_card_region

        # 读取手牌数
        hand_count = _read_hand_count(all_texts, self.width, self.height)
        self.log_info(f"底部手牌数: {hand_count}")

        # 1. 识别手牌区域内的所有文本框
        boxes_in_zone = [b for b in all_texts
                         if x1 <= (b.x + b.width / 2) / self.width <= x2
                         and y1 <= (b.y + b.height / 2) / self.height <= y2]

        self.log_info(f"手牌区域共识别到 {len(boxes_in_zone)} 个文本框")
        for b in boxes_in_zone:
            self.log_info(f"  box: name=「{b.name}」 x={b.x/self.width:.4f} y={b.y/self.height:.4f} w={b.width/self.width:.4f} h={b.height/self.height:.4f}")

        # 2. 分离卡牌名和按键
        # 卡牌名：不含数字按键、长度>1
        # 排除包含"攻击""强化""技能"的文本
        exclude_keywords = ["攻击", "强化", "技能"]
        card_names = [b for b in boxes_in_zone
                      if not _card_key(b.name)
                      and len(b.name) > 1
                      and not any(kw in b.name for kw in exclude_keywords)]

        # 按键：包含数字的
        keys = [(b.x / self.width, b.y / self.height, _card_key(b.name))
                for b in all_texts if _card_key(b.name)]

        self.log_info(f"识别到 {len(card_names)} 张卡牌名: {[b.name for b in card_names]}")
        self.log_info(f"识别到 {len(keys)} 个数字按键: {[(f'{kx:.4f}', f'{ky:.4f}', k) for kx, ky, k in keys]}")

        # 3. 按 x 排序卡牌名和按键
        card_names.sort(key=lambda b: b.x)
        keys.sort(key=lambda x: x[0])

        # 4. 配对：每个卡牌匹配其左上方最近的未使用按键
        used_keys = set()
        cards = []
        for i, name_box in enumerate(card_names):
            cx = name_box.x / self.width
            cy = name_box.y / self.height
            expected_num = i + 1

            # 筛选垂直范围+水平约束的未使用按键
            candidates = []
            for kx, ky, k in keys:
                if k in used_keys:
                    continue
                # 垂直：按键在卡牌名上方 0.03~0.06
                if not (cy - 0.06 <= ky <= cy - 0.03):
                    continue
                # 水平：按键在卡牌名左方，距离不超过 0.025
                if not (cx - 0.025 <= kx <= cx + 0.01):
                    continue
                candidates.append((kx, ky, k))

            if candidates:
                # 取水平最接近的
                best = min(candidates, key=lambda x: cx - x[0])
                used_keys.add(best[2])
                cards.append({"name": name_box.name, "key": best[2], "x": cx,
                              "key_x": best[0], "name_x": cx, "name_y": cy})
            else:
                self.log_info(f"卡牌「{name_box.name}」(x={cx:.4f}) 未找到对应按键（预期按键{expected_num}）")
                cards.append({"name": name_box.name, "key": None, "x": cx,
                              "key_x": None, "name_x": cx, "name_y": cy})

        # 5. 推断OCR遗漏的按键
        # 5a. 先用函数识别到的按键做首次分配
        self.log_info("=== 优化后配对结果 ===")
        for i, c in enumerate(cards):
            if c["key"]:
                self.log_info(f"  卡牌「{c['name']}」 x={c['name_x']:.4f} → 按键 {c['key']} (key_x={c['key_x']:.4f})")
            else:
                self.log_info(f"  卡牌「{c['name']}」 x={c['name_x']:.4f} → 无按键")

        # 5b. 整体推断：用手牌数 x 位置估算每张牌的按键（根据间距百分比）
        self.log_info("=== 间距推断结果 ===")
        if hand_count is not None and len(cards) > 0:
            # 按 x 排序卡牌
            sorted_cards = sorted(enumerate(cards), key=lambda x: x[1]["x"])
            if len(cards) >= 2 and hand_count > 1:
                first_x = sorted_cards[0][1]["x"]
                last_x = sorted_cards[-1][1]["x"]
                total_span = last_x - first_x
                expected_spacing = total_span / (hand_count - 1)

                # 根据位置估算每张卡牌的按键
                for idx, c in sorted_cards:
                    # 用位置插值计算近似按键 (位置0%→按键1, 位置100%→按键hand_count)
                    approx_key = 1 + round((c["x"] - first_x) / expected_spacing)
                    approx_key = min(approx_key, 9)
                    if c["key"] is None:
                        c["key"] = str(approx_key)
                        self.log_info(f"  卡牌「{c['name']}」 x={c['x']:.4f} → 间距推断→ {approx_key}")
                    elif int(c["key"]) != approx_key:
                        self.log_info(f"  卡牌「{c['name']}」 x={c['x']:.4f} → 原按键{c['key']}，间距推断调整为 {approx_key}")
                        c["key"] = str(approx_key)
            else:
                # 只有一张卡牌，直接分配按键1
                for idx, c in sorted_cards:
                    if c["key"] is None:
                        c["key"] = "1"
                        self.log_info(f"  卡牌「{c['name']}」 x={c['x']:.4f} → 间距推断→ 1")
        elif hand_count is None:
            # 无法读取手牌数，用简单推断
            for i, c in enumerate(cards):
                if c["key"] is None:
                    expected = i + 1
                    self.log_info(f"  卡牌「{c['name']}」 x={c['x']:.4f} → 简单推断→ {expected}")
                    c["key"] = str(expected)

        # 最终结果汇总
        self.log_info("=== 最终配对结果 ===")
        for c in cards:
            self.log_info(f"  卡牌「{c['name']}」 x={c['x']:.4f} → 按键 {c['key']}")

        # 6. 旧版结果对比
        self.log_info("=== 旧版配对结果 ===")
        old_keys = [(b.x / self.width, _card_key(b.name)) for b in all_texts if _card_key(b.name)]
        old_used = set()
        for name_box in card_names:
            cx = name_box.x / self.width
            cy = name_box.y / self.height
            candidates = [(kx, k) for kx, k in old_keys
                          if k not in old_used and kx <= cx + 0.04]
            if candidates:
                best = max(candidates, key=lambda x: x[0])
                old_used.add(best[1])
                self.log_info(f"  卡牌「{name_box.name}」 x={cx:.4f} → 旧版匹配按键 {best[1]} (key_x={best[0]:.4f})")
            else:
                self.log_info(f"  卡牌「{name_box.name}」 x={cx:.4f} → 旧版无按键")