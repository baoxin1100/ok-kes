# Test case
import unittest

from PySide6.QtGui import QFontMetrics

from src.config import config
from ok.test.TaskTestCase import TaskTestCase
from ok.gui.tasks.ConfigItemFactory import config_widget
from ok.gui.tasks.LabelAndButtons import LabelAndButtons
from ok.gui.tasks.LabelAndFileSelector import LabelAndFileSelector
from ok.gui.tasks.ModifyListDialog import ModifyListDialog
from ok.gui.tasks.ModifyListItem import ModifyListItem
from qfluentwidgets import PushButton

from src.tasks.MyOneTimeTask import MyOneTimeTask


class TestMyOneTimeTask(TaskTestCase):
    task_class = MyOneTimeTask

    config = config

    def test_config_demo_supports_all_widget_types_and_sub_configs(self):
        defaults = self.task.default_config
        config_type = self.task.config_type

        self.assertIsInstance(defaults["Boolean Config"], bool)
        self.assertIsInstance(defaults["Integer Config"], int)
        self.assertIsInstance(defaults["Float Config"], float)
        self.assertIsInstance(defaults["String Config"], str)
        self.assertIsInstance(defaults["Folder Selector Config"], str)
        self.assertIsInstance(defaults["File Selector Config"], str)
        self.assertIsInstance(defaults["List Config"], list)
        self.assertIsInstance(defaults["Drop Down Options Config"], list)
        self.assertEqual("String Value", defaults["String Config"])
        self.assertEqual(["List Value 1", "List Value 2"], defaults["List Config"])
        self.assertEqual("drop_down", config_type["Drop Down Config"]["type"])
        self.assertEqual("text_edit", config_type["Text Edit Config"]["type"])
        self.assertEqual("file_selector", config_type["Folder Selector Config"]["type"])
        self.assertEqual("folder", config_type["Folder Selector Config"]["selector_type"])
        self.assertEqual("Select Demo Folder", config_type["Folder Selector Config"]["dialog_title"])
        self.assertEqual("file_selector", config_type["File Selector Config"]["type"])
        self.assertEqual("file", config_type["File Selector Config"]["selector_type"])
        self.assertEqual("Select Demo File", config_type["File Selector Config"]["dialog_title"])
        self.assertEqual("Python Files (*.py);;All Files (*)", config_type["File Selector Config"]["filter"])
        self.assertEqual("drop_down", config_type["Drop Down Options Config"]["type"])
        self.assertEqual(
            [
                "Available Drop Down Value 1",
                "Available Drop Down Value 2",
                "Available Drop Down Value 3",
            ],
            config_type["Drop Down Options Config"]["options_available"],
        )
        self.assertEqual("multi_selection", config_type["Multi Selection Config"]["type"])
        self.assertEqual("global", config_type["Game Hotkey Config"]["type"])
        self.assertEqual("button", config_type["Button Config"]["type"])
        self.assertEqual("button", config_type["Button Options Config"]["type"])
        self.assertEqual(
            ["Show Config Values", "Show Notification"],
            [button["text"] for button in config_type["Button Options Config"]["buttons"]],
        )
        self.assertEqual(
            {
                "Drop Down Value 1": ["Sub Boolean Config"],
                "Drop Down Value 2": ["Sub String Config", "Sub Float Config"],
            },
            config_type["Drop Down Config"]["sub_configs"],
        )

    def test_folder_selector_config_uses_folder_selector_widget(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "Folder Selector Config",
            self.task.config.get("Folder Selector Config"),
            self.task,
        )
        self.assertIsInstance(widget, LabelAndFileSelector)
        self.assertEqual("folder", widget.selector_type)
        self.assertFalse(hasattr(widget, "line_edit"))
        self.assertEqual(str(self.task.config.get("Folder Selector Config") or ""), widget.value_label.text())

    def test_file_selector_config_uses_file_selector_widget(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "File Selector Config",
            self.task.config.get("File Selector Config"),
            self.task,
        )
        self.assertIsInstance(widget, LabelAndFileSelector)
        self.assertEqual("file", widget.selector_type)
        self.assertEqual("Python Files (*.py);;All Files (*)", widget.config_type["filter"])
        self.assertFalse(hasattr(widget, "line_edit"))
        self.assertEqual(str(self.task.config.get("File Selector Config") or ""), widget.value_label.text())

    def test_button_options_config_uses_multiple_buttons(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "Button Options Config",
            self.task.config.get("Button Options Config"),
            self.task,
        )
        self.assertIsInstance(widget, LabelAndButtons)
        self.assertEqual(2, len(widget.findChildren(PushButton)))

    def test_options_available_uses_restricted_option_list_dialog(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "Drop Down Options Config",
            self.task.config.get("Drop Down Options Config"),
            self.task,
        )
        self.assertIsInstance(widget, ModifyListItem)
        self.assertTrue(widget.allow_duplication)

        options = self.task.config_type["Drop Down Options Config"]["options_available"]
        dialog = ModifyListDialog(
            ["Available Drop Down Value 1"],
            widget,
            options_available=options,
            allow_duplication=widget.allow_duplication,
        )
        result = []
        dialog.list_modified.connect(result.append)

        dialog.add_available_item("Available Drop Down Value 2")
        dialog.add_available_item("Available Drop Down Value 2")
        dialog.confirm()

        self.assertEqual(
            [
                "Available Drop Down Value 1",
                "Available Drop Down Value 2",
                "Available Drop Down Value 2",
            ],
            result[0],
        )
        widget.list_modified(["Available Drop Down Value 1", "Not Available"])
        self.assertEqual(["Available Drop Down Value 1"], self.task.config["Drop Down Options Config"])

    def test_string_config_input_uses_minimum_width_when_empty(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "String Config",
            self.task.config.get("String Config"),
            self.task,
        )

        widget.line_edit.setText("")
        self.assertEqual(100, widget.line_edit.width())
        self.assertEqual(100, widget.line_edit.minimumWidth())
        widget.line_edit.setText("a")
        self.assertEqual(100, widget.line_edit.width())
        long_text = "String Value With Enough Content"
        widget.line_edit.setText(long_text)
        expected_width = (
            QFontMetrics(widget.line_edit.font()).horizontalAdvance(long_text)
            + widget.HORIZONTAL_PADDING
        )
        self.assertEqual(expected_width, widget.line_edit.width())
        self.task.config["String Config"] = self.task.default_config["String Config"]

    def test_text_edit_config_uses_minimum_width_when_empty(self):
        widget = config_widget(
            self.task.config_type,
            self.task.config_description,
            self.task.config,
            "Text Edit Config",
            self.task.config.get("Text Edit Config"),
            self.task,
        )

        widget.text_edit.setText("")
        self.assertEqual(200, widget.text_edit.width())
        self.assertEqual(200, widget.text_edit.minimumWidth())
        widget.text_edit.setText("a")
        self.assertEqual(200, widget.text_edit.width())
        long_line = "Text Edit Value With Enough Content To Need More Width"
        widget.text_edit.setText(f"Short\n{long_line}")
        expected_width = (
            QFontMetrics(widget.text_edit.font()).horizontalAdvance(long_line)
            + widget.HORIZONTAL_PADDING
        )
        self.assertEqual(expected_width, widget.text_edit.width())
        self.task.config["Text Edit Config"] = self.task.default_config["Text Edit Config"]

    def test_run_shows_config_values(self):
        self.task.config.reset_to_default()
        self.task.run()

        for key, value in self.task.config.items():
            if key != "Game Hotkey Config":
                self.assertEqual(self.task.translate_config_value(value), self.task.info_get(key))
        self.assertEqual(
            dict(self.task.get_global_config("Game Hotkey Config")),
            self.task.info_get("Game Hotkey Config"),
        )
        self.assertEqual("下拉框值 1", self.task.info_get("Drop Down Config"))
        self.assertEqual("bool值 True", self.task.info_get("Boolean Config"))
        self.assertEqual("字符串值", self.task.info_get("String Config"))
        self.assertEqual(["列表值 1", "列表值 2"], self.task.info_get("List Config"))
        self.assertEqual(
            ["可用下拉框值 1"],
            self.task.info_get("Drop Down Options Config"),
        )
        self.assertEqual(
            ["多选值 1", "多选值 2"],
            self.task.info_get("Multi Selection Config"),
        )

    def test_ocr1(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        text = self.task.find_some_text_on_bottom_right()
        self.assertEqual(text[0].name, '商城')

    def test_ocr2(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        text = self.task.find_some_text_with_relative_box()
        self.assertEqual(text[0].name, '招募')

    def test_feature1(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        feature = self.task.test_find_one_feature()
        self.assertIsNotNone(feature)

    def test_feature2(self):
        # Create a BattleReport object
        self.set_image('tests/images/main.png')
        features = self.task.test_find_feature_list()
        self.assertEqual(1, len(features))


if __name__ == '__main__':
    unittest.main()
