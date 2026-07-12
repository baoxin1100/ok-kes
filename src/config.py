import os

import numpy as np
from ok import ConfigOption

version = "v1.2.5"
#不需要修改version, Github Action打包会自动修改

key_config_option = ConfigOption('Game Hotkey Config', { #全局配置示例
    'Echo Key': 'q',
    'Liberation Key': 'r',
    'Resonance Key': 'e',
    'Tool Key': 't',
}, description='In Game Hotkey for Skills')

# 游戏语言配置，全局共享，出击模式和卡厄思模式统一使用
game_language_option = ConfigOption('游戏语言', {
    '游戏语言': '简体中文',
}, config_type={
    '游戏语言': {'type': 'drop_down', 'options': ['简体中文', '繁体中文', '日文', '英文']},
}, description='选择游戏客户端语言，影响OCR文本匹配')


def make_bottom_right_black(frame): #可选. 某些游戏截图时遮挡UID使用
    """
    Changes a portion of the frame's pixels at the bottom right to black.

    Args:
        frame: The input frame (NumPy array) from OpenCV.

    Returns:
        The modified frame with the bottom-right corner blackened.  Returns the original frame
        if there's an error (e.g., invalid frame).
    """
    try:
        height, width = frame.shape[:2]  # Get height and width

        # Calculate the size of the black rectangle
        black_width = int(0.13 * width)
        black_height = int(0.025 * height)

        # Calculate the starting coordinates of the rectangle
        start_x = width - black_width
        start_y = height - black_height

        # Create a black rectangle (NumPy array of zeros)
        black_rect = np.zeros((black_height, black_width, frame.shape[2]), dtype=frame.dtype)  # Ensure same dtype

        # Replace the bottom-right portion of the frame with the black rectangle
        frame[start_y:height, start_x:width] = black_rect

        return frame
    except Exception as e:
        print(f"Error processing frame: {e}")
        return frame

config = {
    'custom_tasks':True, # enable creating and editing custom tasks
    'debug': False,  # Optional, default: False
    'use_gui': True, # 目前只支持True
    'config_folder': 'configs', #最好不要修改
    'global_configs': [key_config_option, game_language_option],
    'screenshot_processor': make_bottom_right_black, # 在截图的时候对frame进行修改, 可选
    'gui_icon': 'icons/icon.png', #窗口图标, 最好不需要修改文件名
    'wait_until_before_delay': 0,
    'wait_until_check_delay': 0,
    'wait_until_settle_time': 0, #调用 wait_until时候, 在第一次满足条件的时候, 会等待再次检测, 以避免某些滑动动画没到预定位置就在动画路径中被检测到
    'ocr': { #可选, 使用的OCR库
        'lib': 'onnxocr',
        'auto_simplify': True, #自动繁体转简体, 需要ppocrv5等可以识别繁体的库
        'params': {
            'use_openvino': True,
        }
    },
    'windows': {  # Windows游戏请填写此设置
        # 'exe': ['ssr-xcent.exe'],
        # optional, if set, will search the exe only
        # 'hwnd_class': 'UnrealWindow', #增加重名检查准确度
        'interaction': ['Pynput', 'PostMessage', 'Genshin', 'PyDirect','ForegroundPostMessage'], # Genshin:某些操作可以后台, 部分游戏支持 PostMessage:可后台点击, 极少游戏支持 ForegroundPostMessage:前台使用PostMessage Pynput/PyDirect:仅支持前台使用
        'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt'],  # Windows版本支持的话, 优先使用WGC, 否则使用BitBlt_Full. 支持的capture有 BitBlt, WGC, BitBlt_RenderFull, DXGI
        'check_hdr': False, #当用户开启AutoHDR时候提示用户, 但不禁止使用
        'force_no_hdr': False, #True=当用户开启AutoHDR时候禁止使用
        'require_bg': True # 要求使用后台截图
    },
    'adb': {  # Windows游戏请填写此设置, mumu模拟器使用原生截图和input,速度极快. 其他模拟器和真机使用adb,截图速度较慢
        # optional, if set, will start the pacakge and ensure installed
        #'packages': ['com.abc.efg1', 'com.abc.efg1']
    },
    'start_timeout': 120,  # default 60
    'window_size': { #ok-script窗口大小
        'width': 1200,
        'height': 800,
        'min_width': 600,
        'min_height': 450,
    },
    'supported_resolution': {
        'ratio': '16:9', #支持的游戏分辨率
        'min_size': (3840, 2160), #设4K，当前任何低于4K的分辨率都会触发try_resize_to缩放到1920x1080
        'resize_to': [(1920, 1080), (1600, 900), (1280, 720)], #优先1920x1080，1080p屏幕放不下则回退至1600x900
        'force_ratio': True, #不弹分辨率报错弹窗，由resize_to处理
    },
    'links': { # 关于里显示的链接, 可选
            'default': {
                'github': 'https://github.com/ok-oldking/ok-py',
                'discord': 'https://discord.gg/vVyCatEBgA',
                'share': 'Download from https://github.com/ok-oldking/ok-py',
                'qq_group':'https://qm.qq.com/q/3Gq4VLvQe',
                'qq_channel': 'https://pd.qq.com/s/djmm6l44y',
                'faq': 'https://github.com/ok-oldking/ok-py'
            }
        },
    'screenshots_folder': "screenshots", #截图存放目录, 每次重新启动会清空目录
    'gui_title': 'ok-py',  #窗口名
    'template_matching': { # 可选, 如使用OpenCV的模板匹配
        'coco_feature_json': os.path.join('ok_tasks/assets', 'coco_annotations.json'), #coco格式标记, 需要png图片, 在debug模式运行后, 会对进行切图仅保留被标记部分以减少图片大小
        'default_horizontal_variance': 0.002, #默认x偏移, 查找不传box的时候, 会根据coco坐标, match偏移box内的
        'default_vertical_variance': 0.002, #默认y偏移
        'default_threshold': 0.8, #默认threshold
    },
    'version': version, #版本
    'my_app': ['src.globals', 'Globals'], #可选. 全局单例对象, 可以存放加载的模型, 使用og.my_app调用
    'onetime_tasks': [  # 用户点击触发的任务
        ["src.tasks.MyOneTimeTask", "MyOneTimeTask"],
        ["ok", "DiagnosisTask"],
    ],
}
