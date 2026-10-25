import ok
from src.config import config
from src.ui.SponsorDialog import install_sponsor_dialog
from src.window_recovery import install_window_recovery

if __name__ == '__main__':
    install_sponsor_dialog()
    install_window_recovery()
    config = config
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
