from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QSizePolicy, QSpacerItem, 
                             QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QApplication)
from qfluentwidgets import SmoothScrollArea, BodyLabel
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QRect, QPoint, QParallelAnimationGroup
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush
from qfluentwidgets import MessageBoxBase, PushButton, PrimaryPushButton, SubtitleLabel
from PyQt6.QtCore import pyqtSignal
import ctypes

class TranslationCard(QWidget):
    def __init__(self, html_content, border_color):
        super().__init__()
        self.border_color = border_color
        self.setMinimumHeight(20)
        
        # Absolute prevention of focus-induced layout shifts
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        
        self.label = BodyLabel(html_content)
        self.label.setWordWrap(True)
        # Disable interaction to prevent the weird shift when clicking text
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.label.setMargin(0)
        self.label.setIndent(0)
        self.label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                outline: none;
                margin: 0px;
                padding: 0px;
            }
        """)
        layout.addWidget(self.label)
        
        # Shadow Effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Animation effects
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(0.0)
        self.label.setGraphicsEffect(self.opacity_effect)
        
        # We animate the whole widget coming in
        self.anim_group = QParallelAnimationGroup(self)
        
        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        self.anim_group.addAnimation(self.fade_anim)
        
    def showEvent(self, event):
        super().showEvent(event)
        self.anim_group.start()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Card Background
        path = QPainterPath()
        from PyQt6.QtCore import QRectF
        rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        path.addRoundedRect(rect, 8.0, 8.0)
        
        # Glassmorphism dark gradient
        painter.fillPath(path, QBrush(QColor(24, 24, 37, 240)))
        
        # Subtle white shine on top
        painter.setPen(QPen(QColor(255, 255, 255, 10), 1))
        painter.drawPath(path)
        
        # Left Accent Border
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(self.border_color)))
        painter.drawRoundedRect(QRect(0, 0, 4, self.height()), 2, 2)


class ResultsPanel(SmoothScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setStyleSheet("""
            QScrollArea { border: none; background: transparent; outline: none; }
            QScrollArea:focus { border: none; outline: none; }
            QWidget#scroll_content { background: transparent; outline: none; border: none; }
            QWidget#scroll_content:focus { outline: none; border: none; }
            QScrollBar:vertical {
                border: none;
                background: #1e1e2e;
                width: 8px;
                margin: 0px 0px 0px 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #414868;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover { background: #565f89; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        
        self.content_widget = QWidget()
        self.content_widget.setObjectName("scroll_content")
        
        # Completely disable focus on scroll viewports to prevent 1px UI shifts on click
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.content_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.scroll_layout = QVBoxLayout(self.content_widget)
        self.scroll_layout.setContentsMargins(10, 6, 10, 10)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.setWidget(self.content_widget)
        
    def clear(self):
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
    def append_html(self, html):
        label = BodyLabel(html)
        label.setWordWrap(True)
        label.setStyleSheet("background: transparent; color: #a9b1d6;")
        self.scroll_layout.addWidget(label)
        self._scroll_to_bottom()
        
    def append_card(self, html, border_color):
        card = TranslationCard(html, border_color)
        self.scroll_layout.addWidget(card)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

class HotkeyInputDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Назначение горячей клавиши")
        self.instructionLabel = BodyLabel("Нажмите любую клавишу, кнопку мыши или геймпада...")
        self.instructionLabel.setStyleSheet("font-size: 16px; font-weight: bold; color: #7aa2f7;")
        self.instructionLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addWidget(self.instructionLabel)
        
        self.captured_keys = set()
        self.final_keys = []
        self.currently_pressing = False
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_inputs)
        self.timer.start(16)
        
        self.user32 = ctypes.windll.user32
        try:
            self.xinput = ctypes.windll.xinput1_4
        except:
            try: self.xinput = ctypes.windll.xinput1_3
            except: self.xinput = None

        self.widget.setMinimumWidth(350)
        self.yesButton.setText("Применить")
        self.cancelButton.setText("Отмена")
        self.yesButton.setEnabled(False)

    def poll_inputs(self):
        try:
            from core.hotkeys import VK_NAMES, XINPUT_BUTTONS, XINPUT_STATE
        except ImportError:
            return

        pressed = set()
        # Keyboard / Mouse
        # Avoid capturing LMouse/RMouse unless combined with something, because click to focus dialog might trigger it
        # Actually, let's just ignore LMouse if it's the only one, or just add a slight delay before polling.
        for vk, name in VK_NAMES.items():
            if self.user32.GetAsyncKeyState(vk) & 0x8000:
                pressed.add(name)
                
        # Gamepad
        if self.xinput:
            state = XINPUT_STATE()
            for i in range(4):
                if self.xinput.XInputGetState(i, ctypes.byref(state)) == 0:
                    buttons = state.Gamepad.wButtons
                    for mask, name in XINPUT_BUTTONS.items():
                        if buttons & mask:
                            pressed.add(name)
        
        # Filter out standalone left click to prevent accidental mapping when clicking the button
        if pressed == {'LMouse'} and not self.currently_pressing:
            pressed = set()

        if pressed:
            if not self.currently_pressing:
                self.captured_keys.clear()
            self.currently_pressing = True
            self.captured_keys.update(pressed)
            self.instructionLabel.setText(" + ".join(sorted(self.captured_keys)))
            self.final_keys = sorted(list(self.captured_keys))
            self.yesButton.setEnabled(True)
        else:
            self.currently_pressing = False

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)


class HotkeyMixin:
    def set_hotkeys(self, keys):
        self.hotkeys = keys
        self.update()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.RightButton:
            dlg = HotkeyInputDialog(self.window())
            if dlg.exec():
                self.hotkeys = dlg.final_keys
                if hasattr(self, 'hotkey_changed'):
                    self.hotkey_changed.emit(self.hotkeys)
                self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if getattr(self, 'hotkeys', None):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            text = " + ".join(self.hotkeys)
            
            font = QFont("Segoe UI", 7)
            font.setBold(True)
            painter.setFont(font)
            
            fm = painter.fontMetrics()
            w = fm.horizontalAdvance(text) + 8
            h = fm.height() + 2
            
            rect = QRect(4, 2, w, h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(122, 162, 247, 240)) # blueish accent
            painter.drawRoundedRect(rect, 3, 3)
            
            painter.setPen(QColor(24, 24, 37))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

class HotkeyedPushButton(HotkeyMixin, PushButton):
    hotkey_changed = pyqtSignal(list)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hotkeys = []

class HotkeyedPrimaryPushButton(HotkeyMixin, PrimaryPushButton):
    hotkey_changed = pyqtSignal(list)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hotkeys = []
