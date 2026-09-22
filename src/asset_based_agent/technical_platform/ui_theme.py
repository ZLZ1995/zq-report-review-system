"""S14 视觉层级和密度：集中调色板、间距刻度、对比度校验。

单一事实源：run_status / message_cards / app 样式必须引用本模块常量。
CONTRAST_PAIRS 中登记的每对（文字, 背景）由测试直接校验，阈值遵循
WCAG AA（正文/状态文字 ≥4.5），不得为通过测试放宽阈值。
"""
from __future__ import annotations

# ------------------------------------------------------------ 文字色

TEXT = '#282b33'
MUTED = '#6b7280'
SIDEBAR_MUTED = '#626875'
LOG = '#5f6b80'
LOG_TEXT = '#66707f'

# ------------------------------------------------------------ 状态色

RUNNING = '#2f5fc4'
ERROR = '#b23a32'
WARNING = '#92600f'
SUCCESS = '#22794b'
UNKNOWN = '#6d4fc4'

# 卡片正文的深色调（与标签同族、更深一档）
WARNING_TEXT = '#8a6d1f'
ERROR_TEXT = '#9a3f38'

# ------------------------------------------------------------ 卡片层级背景

CARD_BG_NEUTRAL = '#fafbfc'
CARD_BG_STATUS = '#f7f9fc'
CARD_BG_WARNING = '#fdf8ec'
CARD_BG_ERROR = '#fdf1f0'
CARD_BG_SUCCESS = '#f2faf5'
USER_CARD_BG = '#f3f4f7'

# ------------------------------------------------------------ 选中态

SELECTION_BG = '#e0e9fb'
SELECTION_TEXT = TEXT

# ------------------------------------------------------------ 密度与版式

SPACING = (4, 8, 12, 16, 24, 32)
MAX_CONTENT_WIDTH = 1080
LOG_FONT_SIZE = 11
LOG_LINE_HEIGHT = 140

# ------------------------------------------------------------ 对比度登记

CONTRAST_PAIRS = (
    ('正文', TEXT, '#ffffff', 4.5),
    ('次要文字', MUTED, '#ffffff', 4.5),
    ('侧栏次要', SIDEBAR_MUTED, '#f5f5f7', 4.5),
    ('选中项', SELECTION_TEXT, SELECTION_BG, 4.5),
    ('运行中状态色', RUNNING, CARD_BG_STATUS, 4.5),
    ('错误色', ERROR, CARD_BG_ERROR, 4.5),
    ('错误正文', ERROR_TEXT, CARD_BG_ERROR, 4.5),
    ('警告色', WARNING, CARD_BG_WARNING, 4.5),
    ('警告正文', WARNING_TEXT, CARD_BG_WARNING, 4.5),
    ('成功色', SUCCESS, CARD_BG_SUCCESS, 4.5),
    ('未知状态色', UNKNOWN, CARD_BG_STATUS, 4.5),
    ('系统日志标签', LOG, CARD_BG_NEUTRAL, 4.5),
    ('系统日志正文', LOG_TEXT, CARD_BG_NEUTRAL, 4.5),
    ('用户卡标签', LOG, USER_CARD_BG, 4.5),
)


def _luminance(color: str) -> float:
    value = color.lstrip('#')
    red, green, blue = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def linear(channel: float) -> float:
        return (channel / 12.92 if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4)

    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 对比度。"""
    low, high = sorted((_luminance(foreground), _luminance(background)))
    return (high + 0.05) / (low + 0.05)


def qss_overrides() -> str:
    """追加在基础样式表之后的覆盖层（QSS 同级选择器后者生效）。"""
    return f"""
            QLabel#muted {{ color:{MUTED}; }}
            QLabel#sectionLabel {{ color:{SIDEBAR_MUTED}; }}
            QLabel#account {{ color:{SIDEBAR_MUTED}; }}
            QLabel#status {{ color:{SIDEBAR_MUTED}; }}
            QPushButton#mutedButton {{ color:{SIDEBAR_MUTED}; }}
            QComboBox {{ color:{SIDEBAR_MUTED}; }}
            QListWidget::item:selected, QTreeWidget#projectTree::item:selected {{
                background:{SELECTION_BG}; color:{SELECTION_TEXT};
                border-left:3px solid {RUNNING};
            }}
            QTreeWidget#projectTree {{ selection-background-color:{SELECTION_BG}; }}
            QTabBar::tab {{ color:{SIDEBAR_MUTED}; }}
            QTabBar::tab:selected {{ color:{TEXT}; border-bottom:2px solid {RUNNING}; }}
        """
