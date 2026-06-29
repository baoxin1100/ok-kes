import ok
import sys
import os
from src.config import config

if __name__ == '__main__':
    # PyInstaller --onefile mode: 切换数据目录，但配置文件保存在 exe 所在位置
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(sys._MEIPASS)
        config["config_folder"] = os.path.join(exe_dir, "configs")
    config = config
    ok = ok.OK(config)
    ok.start()
