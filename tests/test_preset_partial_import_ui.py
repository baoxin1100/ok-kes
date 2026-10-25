import copy
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ok_tasks"))

from PySide6.QtWidgets import QApplication, QDialog

import preset_deck as deck
import preset_deck_import as importer
import preset_deck_ui as ui


class PartialImportEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original = [{"name": "原卡牌", "effects": ["原效果"],
                          "divine_text": [], "reject_divine": False}]
        self.task = SimpleNamespace(config={"预设卡组": copy.deepcopy(self.original), "游戏语言": "简体中文"})
        self.result = importer.convert_preset({"cards": [
            {"cardId": "c_1039_srt4", "variantCardId": "c_1039_srt4_rsp2", "divineId": "missing"},
            {"cardId": "card_ne_00050", "epiphanyId": "c00002"}]})

    def test_partial_import_is_visible_without_committing_and_cancel_preserves_config(self):
        editor = ui.PresetDeckDialog(self.task)
        with patch.object(ui, "DeckCodeImportDialog") as import_dialog, patch.object(ui, "QMessageBox") as message:
            import_dialog.return_value.exec.return_value = QDialog.Accepted
            import_dialog.return_value.result_data = self.result
            editor._import_code()
            self.assertEqual(editor.table.rowCount(), 2)
            self.assertEqual(editor.table.horizontalHeaderItem(4).text(), "导入提示")
            self.assertIn("神闪", editor.table.item(0, 4).text())
            self.assertEqual(editor.table.item(1, 4).text(), "")
            self.assertEqual(editor.table.item(0, 4).toolTip(), editor.table.item(0, 4).text())
            message.return_value.setDetailedText.assert_called_once()
            self.assertIn("missing", message.return_value.setDetailedText.call_args.args[0])
        self.assertEqual(self.task.config["预设卡组"], self.original)
        editor.reject()
        self.assertEqual(self.task.config["预设卡组"], self.original)

    def test_notes_survive_save_normalization_and_reopening(self):
        records = self.result[0]
        with patch.object(ui, "PresetDeckDialog") as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.records = copy.deepcopy(records)
            ui.open_preset_deck_editor(self.task)
        self.assertEqual(deck.load_preset_records(self.task), records)
        editor = ui.PresetDeckDialog(self.task)
        self.assertEqual(editor.records, records)
        self.assertTrue(editor.table.item(0, 4).text())
        editor.close()

    def test_manual_completion_clears_notes_and_keeps_user_fields(self):
        record = copy.deepcopy(self.result[0][0])
        dialog = ui.PresetCardDialog(record=record)
        dialog.divine_edit.setPlainText("抽取1")
        dialog._accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.record["divine_text"], ["抽取1"])
        self.assertEqual(dialog.record["effects"], record["effects"])
        self.assertNotIn("import_notes", dialog.record)
        self.assertIn("import_notes", record)
        dialog.close()

    def test_general_epiphany_matches_modifier_rather_than_common_base_effect(self):
        record = self.result[0][1]
        self.assertEqual(record["effects"], ["士气2"])
        self.assertTrue(deck._text_matches(record["effects"][0], "获得25治愈 士气2"))
        self.assertFalse(deck._text_matches(record["effects"][0], "获得25治愈 士气1"))


if __name__ == "__main__":
    unittest.main()
