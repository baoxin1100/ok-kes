import ok
from src.config import config
from src.ui.SponsorDialog import install_sponsor_dialog

if __name__ == '__main__':
    install_sponsor_dialog()
    config = config
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
