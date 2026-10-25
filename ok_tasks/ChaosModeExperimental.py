"""自动卡厄思模式（实验）。

除“预设卡组”外，其余配置和行为与自动卡厄思模式完全一致：
- 首次创建时自动继承 configs/ChaosMode.json 的当前配置
- 旧版“闪光优先级”会转换为预设卡组的初始记录
- 任务配置独立保存在 configs/ChaosModeExperimental.json
"""
import os

from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file

from ChaosMode import ChaosMode
from preset_deck import convert_legacy_flash_priority
from utils import _disable_other_chaos_tasks


class ChaosModeExperimental(ChaosMode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动卡厄思模式（实验）"
        self.preset_deck_enabled = True
        self.description = (
            "1. 请主动打开游戏内自动战斗和自动剧情功能。\n"
            "2. 国际服玩家请将本模式配置中的\"游戏语言\"设置为繁体中文。\n"
            "3. 实验功能：灵光一闪/神闪按「预设卡组」选择；效果和神闪都不符合时，"
            "在非神闪卡里随机选，三张全神闪选第一张。"
        )

        # 用“预设卡组”替换“闪光优先级”，并保持原来的配置显示顺序。
        rebuilt_defaults = {}
        for key, value in self.default_config.items():
            if key in ("闪光优先级", "需要冥想的卡牌"):
                continue
            if key == "移除卡牌列表" and "预设卡组" not in rebuilt_defaults:
                rebuilt_defaults["预设卡组"] = []
            rebuilt_defaults[key] = value
        if "预设卡组" not in rebuilt_defaults:
            rebuilt_defaults["预设卡组"] = []
        self.default_config = rebuilt_defaults

        self.config_description.pop("闪光优先级", None)
        self.config_description.pop("不要神之一闪", None)
        self.config_description.pop("需要冥想的卡牌", None)
        self.config_description["预设卡组"] = (
            "按列表从上到下匹配。一条记录代表一张卡，需要两张就复制一条。\n"
            "匹配顺序：卡牌名 → 卡牌效果 → 神闪效果。\n"
            "效果和神闪效果填写能唯一识别界面文字的关键字即可，可多行。\n"
            "每条记录可以单独勾选“拒绝神闪”：这张卡出现神闪形态时不选它。\n"
            "编辑窗口支持从官方卡组码联网导入；成功后覆盖列表，保存后生效。\n"
            "卡牌效果和神闪效果都不符合时：在非神闪卡里随机选；三张全神闪选第一张。"
        )
        self.config_type["预设卡组"] = {
            "type": "button",
            "buttons": [
                {
                    "text": "修改",
                    "callback": self._edit_preset_deck,
                }
            ],
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _config_file_name(class_name):
        return f"{class_name}.json"

    def _seed_from_chaos_config(self):
        """首次创建实验模式时，继承普通模式的当前配置。"""
        own_file = get_relative_path(
            Config.config_folder,
            self._config_file_name(self.__class__.__name__),
        )
        if os.path.exists(own_file):
            return
        parent_file = get_relative_path(
            Config.config_folder,
            self._config_file_name("ChaosMode"),
        )
        data = read_json_file(parent_file)
        if not isinstance(data, dict):
            return
        legacy = data.get("闪光优先级", [])
        preset_records = convert_legacy_flash_priority(legacy)
        # 让“预设卡组”出现在原来“闪光优先级”的位置，保持配置界面顺序一致。
        seeded = {}
        inserted = False
        for key, value in data.items():
            if key == "闪光优先级":
                seeded["预设卡组"] = preset_records
                inserted = True
                continue
            if key == "预设卡组":
                continue
            seeded[key] = value
        if not inserted:
            seeded["预设卡组"] = preset_records
        # 实验模式首次创建默认不自动开启，避免重启后两个模式互相抢占。
        seeded["_enabled"] = False
        write_json_file(own_file, seeded)
        try:
            self.log_info(
                f"已从自动卡厄思模式继承配置，"
                f"并将{len(preset_records)}条闪光优先级转换为预设卡组"
            )
        except Exception:
            pass

    def load_config(self):
        self._seed_from_chaos_config()
        super().load_config()

    # ------------------------------------------------------------------
    def _edit_preset_deck(self):
        try:
            from preset_deck_ui import open_preset_deck_editor

            open_preset_deck_editor(self)
        except Exception as exc:
            self.log_error("打开预设卡组编辑器失败", exc)
            try:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    None, "错误", f"打开预设卡组编辑器失败：{exc}"
                )
            except Exception:
                pass

    def enable(self):
        """开启实验模式时关闭普通卡厄思、出击、剧情模式。"""
        _disable_other_chaos_tasks(self)
        super().enable()
