from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, SubtitleLabel, isDarkTheme

from ok.gui.about.LinksBar import LinksBar
from ok.util.file import get_path_relative_to_exe


class SponsorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sponsorDialog")
        self.setWindowTitle("赞赏支持")
        self.setMinimumWidth(720)
        background = "#202020" if isDarkTheme() else "#f0f4f9"
        foreground = "#ffffff" if isDarkTheme() else "#1d1d1d"
        self.setStyleSheet(
            f"QDialog#sponsorDialog {{ background-color: {background}; }}"
            f"QDialog#sponsorDialog QLabel {{ color: {foreground}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        title = SubtitleLabel("赞赏支持", self)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        description = BodyLabel("如果喜欢这个工具，可以赞赏up主持续开发~感谢", self)
        description.setAlignment(Qt.AlignCenter)
        layout.addWidget(description)

        codes_layout = QHBoxLayout()
        codes_layout.setSpacing(24)
        codes_layout.addWidget(self._create_code("微信赞赏", "docs/images/wechat_reward_code.png"))
        codes_layout.addWidget(self._create_code("支付宝赞赏", "docs/images/alipay_reward_code.png"))
        layout.addLayout(codes_layout)

    def _create_code(self, title: str, relative_path: str) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        image = QLabel(container)
        image.setAlignment(Qt.AlignCenter)
        image_path = Path(get_path_relative_to_exe(relative_path))
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            image.setText(f"无法加载图片：{image_path}")
        else:
            image.setPixmap(pixmap.scaled(300, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(image)

        caption = BodyLabel(title, container)
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)
        return container


def install_sponsor_dialog():
    if getattr(LinksBar, "_ok_kes_sponsor_installed", False):
        return

    original_open_url = LinksBar.open_url

    def open_url(links_bar, url_name):
        if url_name == "sponsor":
            dialog = SponsorDialog(links_bar.window())
            dialog.exec()
            return
        original_open_url(links_bar, url_name)

    LinksBar.open_url = open_url
    LinksBar._ok_kes_sponsor_installed = True
