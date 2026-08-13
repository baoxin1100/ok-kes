import ok
import sys
import os
import traceback
from src.config import config
from src.ui.SponsorDialog import install_sponsor_dialog

if __name__ == '__main__':
    try:
        install_sponsor_dialog()
        # PyInstaller --onefile mode: 切换数据目录，但配置文件保存在 exe 所在位置
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            os.chdir(sys._MEIPASS)
            config["config_folder"] = os.path.join(exe_dir, "configs")
        config = config
        ok = ok.OK(config)
        ok.start()
    except Exception as e:
        log_path = os.path.join(os.path.dirname(sys.executable), "error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Error: {e}\n\n")
            traceback.print_exc(file=f)
        raise
