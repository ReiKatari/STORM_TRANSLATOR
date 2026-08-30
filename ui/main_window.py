from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QGraphicsDropShadowEffect, QSizeGrip, QTextEdit, QApplication, QPushButton as QtPushButton
from qfluentwidgets import (PushButton, PrimaryPushButton, ComboBox, CheckBox, DoubleSpinBox, 
                            Slider, SubtitleLabel, BodyLabel, TitleLabel, setTheme, Theme, 
                            CardWidget, ScrollArea, TransparentToolButton, ToolButton)
from PyQt6.QtCore import Qt, QRect, QPoint, QTimer
from PyQt6.QtGui import QColor
from core.settings import SettingsManager
from resources.lang import LANGUAGES
from resources.themes import THEMES
from ui.components import ResultsPanel, HotkeyedPushButton, HotkeyedPrimaryPushButton

class CollapsibleWidget(QWidget):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self.header = PushButton(title)
        self.header.setObjectName("collapsible_header")
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setFixedHeight(35)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setStyleSheet("""
            QPushButton#collapsible_header {
                background-color: #1a1b26;
                color: #7aa2f7;
                border: 1px solid #2f334d;
                border-radius: 4px;
                text-align: left;
                padding-left: 10px;
                font-weight: bold;
            }
            QPushButton#collapsible_header:checked {
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
            }
        """)
        
        self.content = QWidget()
        self.content.setObjectName("collapsible_content")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(2)
        
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(50)
        self.scroll.setMaximumHeight(200)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.content)
        self.scroll.setStyleSheet("background: transparent;")
        
        self.layout.addWidget(self.header)
        self.layout.addWidget(self.scroll)
        
        self.header.toggled.connect(self.toggle_content)
        
    def toggle_content(self, checked):
        self.scroll.setVisible(checked)
        
    def setTitle(self, title):
        self.header.setText(title)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings_manager = SettingsManager()
        self.is_loading = True
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Load Geometry
        g = self.settings_manager.get('geometry')
        self.setGeometry(g[0], g[1], g[2], g[3])
        
        
        self.langs = LANGUAGES
        self.current_lang = self.settings_manager.get('ui_lang')
        
        # 1. State/Data Initialization (MUST be before setup_ui for Area Manager)
        s = self.settings_manager
        self.AREA_COLORS = ["#FF79C6", "#50FA7B", "#8BE9FD", "#BD93F9", "#FFB86C", "#FF5555", "#F1FA8C"]
        
        areas_data = s.get('translation_areas', [])
        self.translation_areas = [QRect(*a) for a in areas_data]
        
        enabled_data = s.get('areas_enabled', [])
        if len(enabled_data) < len(self.translation_areas):
            enabled_data.extend([True] * (len(self.translation_areas) - len(enabled_data)))
        self.areas_enabled = enabled_data
        
        zones_data = s.get('exclusion_zones', [])
        self.exclusion_zones = [QRect(*z) for z in zones_data]
        
        # Initialize exclusion_zones_enabled based on exclusion_zones
        exclusion_enabled_data = s.get('exclusion_zones_enabled', [])
        if len(exclusion_enabled_data) < len(self.exclusion_zones):
            exclusion_enabled_data.extend([True] * (len(self.exclusion_zones) - len(exclusion_enabled_data)))
        self.exclusion_zones_enabled = exclusion_enabled_data
        
        self.worker = None
        self.translation_overlay = None # Corrected name
        self.selector = None
        self._drag_pos = None
        
        # Mappings for robust saving/loading
        self.SRC_LANGS = ['Auto', 'English', 'Russian', 'Japanese', 'Chinese', 'Korean', 'German', 'French']
        self.TGT_LANGS = ['Russian', 'English', 'Japanese', 'Chinese', 'Korean', 'German', 'French']
        self.OCR_ENGINES = ["EasyOCR", "Tesseract", "MultiOCR"]

        from core.hotkeys import HotkeyManager
        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.hotkey_triggered.connect(self.on_hotkey_triggered)

        # Dummy focus widget for auto-pausing games by removing focus
        self.dummy_focus_widget = QWidget()
        self.dummy_focus_widget.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.dummy_focus_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.dummy_focus_widget.setGeometry(-1000, -1000, 1, 1)
        self.dummy_focus_widget.show()
        self.last_game_hwnd = None

        # 2. Build UI
        self.setup_ui()
        # Ensure dark theme is applied initially
        setTheme(Theme.DARK)
        
        # 3. Update UI text/combos FIRST
        self.update_ui_text()
        
        # 4. Apply settings (including enforcing defaults) LAST
        self.apply_saved_settings()
        
        # Auto-update Check
        if self.settings_manager.get('auto_update'):
            from core.updater import Updater
            from PyQt6.QtWidgets import QMessageBox
            new_v = Updater.check_for_updates()
            if new_v:
                t = self.langs[self.current_lang]
                msg = t['update_msg'].format(curr=Updater.VERSION, new=new_v)
                reply = QMessageBox.question(self, t['update_found'], msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.log_notification(t['updating'])
                    self.close()
                    
        # 5. Dependency Checker
        QTimer.singleShot(1000, self.check_dependencies)
        
        # --- SPEED OPTIMIZATIONS v0.4.1 ---
        # 1. Initialize OCR Manager instance
        from core.ocr import OCRManager
        self._ocr_prewarm = OCRManager()
        
        # 2. Check GPU status and warmup engines in background to avoid freezing UI
        import threading
        def _gpu_and_warmup():
            gpu = self._ocr_prewarm.check_gpu_status()
            t = self.langs[self.current_lang]
            if gpu == "CUDA":
                status_text = t.get('gpu_status_cuda', 'GPU: CUDA ✓')
                color = "#50fa7b"
            elif gpu == "MPS":
                status_text = t.get('gpu_status_mps', 'GPU: MPS ✓')
                color = "#50fa7b"
            else:
                status_text = t.get('gpu_status_cpu', 'GPU: None (CPU)')
                color = "#ff79c6"
                
            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt, Q_ARG
            QMetaObject.invokeMethod(self.gpu_status_label, "setText", QtCore_Qt.ConnectionType.QueuedConnection, Q_ARG(str, status_text))
            QMetaObject.invokeMethod(self.gpu_status_label, "setStyleSheet", QtCore_Qt.ConnectionType.QueuedConnection, Q_ARG(str, f"color: {color}; font-size: 10px;"))
            
            # Now run the heavy warmup
            self._ocr_prewarm.warmup()
            
        threading.Thread(target=_gpu_and_warmup, daemon=True).start()

        self.is_loading = False

    def check_dependencies(self):
        missing = []
        
        # Check Tesseract
        from core.ocr import OCRManager
        ocr_mgr = OCRManager()
        tess_found = ocr_mgr.is_tesseract_installed()
        
        if not tess_found:
            skip_prompt = self.settings_manager.get('skip_tesseract_prompt', False)
            if not skip_prompt:
                from PyQt6.QtWidgets import QMessageBox, QCheckBox
                from PyQt6.QtGui import QDesktopServices
                from PyQt6.QtCore import QUrl
                
                msg = QMessageBox(self)
                msg.setWindowTitle("Рекомендуется установить Tesseract OCR")
                msg.setText("Tesseract OCR — это один из лучших бесплатных движков для быстрого распознавания пиксельных шрифтов без использования GPU.\n\nОн сейчас не установлен.\nХотите перейти на сайт разработчика и скачать его?")
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                
                cb = QCheckBox("Больше не показывать")
                msg.setCheckBox(cb)
                
                res = msg.exec()
                
                if cb.isChecked():
                    self.settings_manager.set('skip_tesseract_prompt', True)
                    self.settings_manager.save()
                    
                if res == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl("https://tesseract-ocr.github.io/tessdoc/Installation.html"))
        
        # Check CUDA
        try:
            import torch
            if not torch.cuda.is_available():
                missing.append("NVIDIA CUDA (Необходимо для мгновенной работы EasyOCR)")
        except:
            missing.append("NVIDIA CUDA / PyTorch GPU")
            
        if missing:
            from qfluentwidgets import MessageBox
            msg_text = "<b>Обнаружены неоптимальные настройки окружения:</b><br><br>"
            msg_text += "<br>".join([f"• {m}" for m in missing])
            msg_text += "<br><br><i>Приложение работает в штатном режиме, но скорость перевода может быть ограничена процессором (CPU).</i>"
            
            w = MessageBox("Dependency Checker", msg_text, self)
            w.yesButton.setText("Понятно")
            w.cancelButton.hide()
            w.show()

    def apply_saved_settings(self):
        s = self.settings_manager
        self.ui_lang_combo.setCurrentIndex(0 if self.current_lang == 'RU' else 1)
        self.aggregate_chk.setChecked(s.get('aggregate'))
        self.auto_update_chk.setChecked(s.get('auto_update', True))
        if hasattr(self, 'tts_chk'):
            self.tts_chk.setChecked(s.get('tts_enabled', False))
        
        # Standards for v0.1.28: Use saved values, but migrate old format if needed
        # (Defaults are handled by SettingsManager)
        
        # Geometry: Ensure at least current defaults for v0.1.20
        # Only force if it's smaller than desired
        curr_g = s.get('geometry')
        curr_g = s.get('geometry')
        if curr_g[2] < 1100 or curr_g[3] < 670:
            s.set('geometry', [curr_g[0], curr_g[1], 1100, 670])
            s.save()
        
        self.setGeometry(*s.get('geometry'))
            
        # Strict migration to ensure correct defaults and override broken configs
        curr_src = s.get('src_lang')
        if curr_src not in ['English', 'Russian', 'Japanese', 'Chinese', 'Korean', 'German', 'French']:
            s.set('src_lang', 'English')
            
        curr_tgt = s.get('target_lang')
        if curr_tgt not in ['Russian', 'English', 'Japanese', 'Chinese', 'Korean', 'German', 'French'] or curr_tgt == s.get('src_lang'):
            s.set('target_lang', 'Russian')
            
        curr_ocr = s.get('ocr_engine')
        if curr_ocr not in ['EasyOCR', 'Tesseract', 'MultiOCR']:
            s.set('ocr_engine', 'EasyOCR')
            
        # Try to restore selection using mapping
        src_data = s.get('src_lang', 'English')
        target_data = s.get('target_lang', 'Russian')
        ocr_data = s.get('ocr_engine', 'EasyOCR')

        try:
            idx_src = self.SRC_LANGS.index(src_data)
        except ValueError:
            idx_src = 1 # English
        self.src_lang_combo.setCurrentIndex(idx_src)
        
        try:
            idx_tgt = self.TGT_LANGS.index(target_data)
        except ValueError:
            idx_tgt = 0 # Russian
        self.target_lang_combo.setCurrentIndex(idx_tgt)

        try:
            idx_ocr = self.OCR_ENGINES.index(ocr_data)
        except ValueError:
            idx_ocr = 2 # EasyOCR
        self.ocr_engine_combo.setCurrentIndex(idx_ocr)

        self.engine_combo.setCurrentText(s.get('engine'))
        self.interval_spin.setValue(s.get('interval'))
        self.silent_mode_chk.setChecked(s.get('silent'))
        self.aggregate_chk.setChecked(s.get('aggregate'))
        self.auto_update_chk.setChecked(s.get('auto_update'))
        if hasattr(self, 'retroarch_chk'):
            self.retroarch_chk.setChecked(s.get('retroarch_pause', False))
        
        self.opacity_slider.setValue(s.get('opacity', 100))
        self.change_opacity(self.opacity_slider.value())
        
        # Hotkeys
        hotkeys = s.get('hotkeys', {})
        if 'start_btn' in hotkeys:
            self.start_btn.set_hotkeys(hotkeys['start_btn'])
            self.hotkey_manager.set_binding('start_btn', hotkeys['start_btn'])
        if 'now_btn' in hotkeys:
            self.now_btn.set_hotkeys(hotkeys['now_btn'])
            self.hotkey_manager.set_binding('now_btn', hotkeys['now_btn'])
        if 'clear_btn' in hotkeys:
            self.clear_btn.set_hotkeys(hotkeys['clear_btn'])
            self.hotkey_manager.set_binding('clear_btn', hotkeys['clear_btn'])
        
        # Pin
        if s.get('on_top', False):
            self.pin_btn.setChecked(True)
            self.toggle_pin(True)
        
        # Theme
        current_theme = s.get('theme', 'Dark (Default)')
        if self.theme_combo.findText(current_theme) >= 0:
            self.theme_combo.setCurrentText(current_theme)
        self.apply_theme(current_theme)
        
        if self.translation_areas:
            from ui.overlay import TranslationOverlay
            from PyQt6.QtWidgets import QApplication
            if not self.translation_overlay:
                self.translation_overlay = TranslationOverlay()
                
                # IMPORTANT: Set overlay to cover the entire virtual desktop (all screens combined)
                # Otherwise, if the main window and game are on different screens, coordinates will offset.
                rect = QApplication.primaryScreen().virtualGeometry() 
                self.translation_overlay.setGeometry(rect)
            
            # Show only enabled areas
            active = [self.translation_areas[i] for i, e in enumerate(self.areas_enabled) if e]
            colors = [self.AREA_COLORS[i % len(self.AREA_COLORS)] for i, e in enumerate(self.areas_enabled) if e]
            self.translation_overlay.set_active_areas(active, colors)
            
        # Initialize lists
        self.refresh_areas_list()
        self.refresh_exclusion_zones_list()

    def setup_ui(self):
        # Allow resizing
        self.setMinimumSize(600, 400)
        
        # Main container
        self.main_container = QWidget(self)
        self.main_container.setObjectName("main_container")
        self.setCentralWidget(self.main_container)
        
        # Layout: Horizontal to separate controls and results
        main_layout = QHBoxLayout(self.main_container)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        

        # LEFT: Controls (Settings)
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(440) 
        self.left_panel.setObjectName("left_panel")
        controls_layout = QVBoxLayout(self.left_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(12)
        
        # Title bar
        title_layout = QHBoxLayout()
        self.title_label = TitleLabel("STORM TRANSLATOR 0.9.0")
        self.title_label.setObjectName("title")
        title_layout.addWidget(self.title_label)
        
        title_layout.addStretch()
        self.pin_btn = ToolButton()
        self.pin_btn.setFixedSize(30, 30)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setObjectName("pin_btn")
        self.pin_btn.clicked.connect(self.toggle_pin)
        title_layout.addWidget(self.pin_btn)
        
        controls_layout.addLayout(title_layout)
        
        # Interface Language selection
        self.ui_lang_label = BodyLabel("Language")
        controls_layout.addWidget(self.ui_lang_label)
        self.ui_lang_combo = ComboBox()
        self.ui_lang_combo.addItems(["Русский", "English"])
        self.ui_lang_combo.currentIndexChanged.connect(self.change_ui_lang)
        controls_layout.addWidget(self.ui_lang_combo)

        # OCR Engine selection
        self.ocr_engine_label = BodyLabel("OCR Engine")
        controls_layout.addWidget(self.ocr_engine_label)
        self.ocr_engine_combo = ComboBox()
        # Only list engines that actually work on this system
        self.ocr_engine_combo.addItems(["EasyOCR", "Tesseract", "MultiOCR"])
        self.ocr_engine_combo.currentIndexChanged.connect(self.save_settings)
        controls_layout.addWidget(self.ocr_engine_combo)
        
        # GPU Status label (informational)
        self.gpu_status_label = BodyLabel("GPU: Checking...")
        self.gpu_status_label.setStyleSheet("color: #888; font-size: 10px;")
        controls_layout.addWidget(self.gpu_status_label)

        # Language Selection (Source & Target)
        langs_layout = QHBoxLayout()
        
        src_v = QVBoxLayout()
        self.src_lang_label = BodyLabel("From")
        src_v.addWidget(self.src_lang_label)
        self.src_lang_combo = ComboBox()
        self.src_lang_combo.addItems(["Auto", "English", "Russian", "Japanese", "Chinese", "Korean", "German", "French"])
        src_v.addWidget(self.src_lang_combo)
        langs_layout.addLayout(src_v)
        
        target_v = QVBoxLayout()
        self.target_lang_label = BodyLabel("To")
        target_v.addWidget(self.target_lang_label)
        self.target_lang_combo = ComboBox()
        self.target_lang_combo.addItems(["Russian", "English", "Japanese", "Chinese", "Korean", "German", "French"])
        target_v.addWidget(self.target_lang_combo)
        langs_layout.addLayout(target_v)
        
        controls_layout.addLayout(langs_layout)

        # Engine Selection
        self.engine_label = BodyLabel("Translation Engine")
        self.engine_label.setStyleSheet("margin-top: 5px;")
        controls_layout.addWidget(self.engine_label)
        self.engine_combo = ComboBox()
        self.engine_combo.addItems(["Google", "DeepL", "Yandex", "Bing", "Papago", "Baidu", "DeepSeek", "ArgosOffline"])
        controls_layout.addWidget(self.engine_combo)
        
        # Modes — 2 rows × 2 columns to prevent text clipping
        from PyQt6.QtWidgets import QGridLayout
        modes_grid = QGridLayout()
        modes_grid.setHorizontalSpacing(8)
        modes_grid.setVerticalSpacing(4)
        
        self.silent_mode_chk = CheckBox("Тихий режим")
        self.silent_mode_chk.setMinimumWidth(140)
        modes_grid.addWidget(self.silent_mode_chk, 0, 0)
        
        self.aggregate_chk = CheckBox("Агрегация")
        self.aggregate_chk.setMinimumWidth(120)
        modes_grid.addWidget(self.aggregate_chk, 0, 1)
        
        self.retroarch_chk = CheckBox("Авто-пауза (Фокус)")
        self.retroarch_chk.setToolTip("Авто-пауза RetroArch (UDP) или любой другой игры (снятие фокуса) при ручном переводе")
        self.retroarch_chk.setMinimumWidth(140)
        modes_grid.addWidget(self.retroarch_chk, 1, 0)

        self.auto_update_chk = CheckBox("Авто-обновление")
        self.auto_update_chk.setMinimumWidth(140)
        self.auto_update_chk.setStyleSheet("QCheckBox::indicator:checked { background-color: #27ae60; border: 1px solid #27ae60; }")
        modes_grid.addWidget(self.auto_update_chk, 1, 1)
        
        self.tts_chk = CheckBox("Озвучка (TTS)")
        self.tts_chk.setMinimumWidth(140)
        self.tts_chk.setToolTip("Автоматически озвучивать переведенный текст")
        modes_grid.addWidget(self.tts_chk, 2, 0)
        
        controls_layout.addLayout(modes_grid)
        
        # Theme Selection
        self.theme_label = BodyLabel("Theme:")
        controls_layout.addWidget(self.theme_label)
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.currentTextChanged.connect(self.apply_theme)
        controls_layout.addWidget(self.theme_combo)
        
        # Interval Selection
        interval_layout = QHBoxLayout()
        self.interval_label = BodyLabel("Interval")
        interval_layout.addWidget(self.interval_label)
        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0.1, 10.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(" s")
        interval_layout.addWidget(self.interval_spin)
        controls_layout.addLayout(interval_layout)
        
        # Opacity Selection
        opacity_layout = QHBoxLayout()
        self.opacity_label = BodyLabel("Opacity")
        opacity_layout.addWidget(self.opacity_label)
        self.opacity_slider = Slider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setMinimumWidth(100)
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        opacity_layout.addWidget(self.opacity_slider)
        
        self.opacity_value_label = BodyLabel("100%")
        self.opacity_value_label.setMinimumWidth(40)
        opacity_layout.addWidget(self.opacity_value_label)
        
        controls_layout.addLayout(opacity_layout)
        
        controls_layout.addStretch()

        self.start_btn = HotkeyedPrimaryPushButton("AUTO-TRANSLATE")
        self.start_btn.setMinimumHeight(45)
        self.start_btn.setObjectName("action_btn")
        controls_layout.addWidget(self.start_btn)
        
        manual_btns_layout = QHBoxLayout()
        manual_btns_layout.setSpacing(5)
        
        self.now_btn = HotkeyedPushButton("MANUAL START")
        self.now_btn.setMinimumHeight(40)
        self.now_btn.setMinimumWidth(135)
        self.now_btn.setObjectName("now_btn")
        
        from PyQt6.QtWidgets import QSizePolicy
        self.now_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.clear_btn = HotkeyedPushButton("MANUAL CLEAR")
        self.clear_btn.setMinimumHeight(40)
        self.clear_btn.setMinimumWidth(135)
        self.clear_btn.setObjectName("clear_btn")
        self.clear_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        manual_btns_layout.addWidget(self.now_btn)
        manual_btns_layout.addWidget(self.clear_btn)
        
        controls_layout.addLayout(manual_btns_layout)
        
        main_layout.addWidget(self.left_panel, 0)

        # MIDDLE: Area Management
        self.mid_panel = QWidget()
        self.mid_panel.setFixedWidth(280)
        self.mid_panel.setObjectName("mid_panel")
        mid_layout = QVBoxLayout(self.mid_panel)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(5)
        mid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.select_area_btn = PushButton("Select Area")
        mid_layout.addWidget(self.select_area_btn)
        
        self.areas_collapsible = CollapsibleWidget("Areas")
        mid_layout.addWidget(self.areas_collapsible)
        self.areas_list_layout = self.areas_collapsible.content_layout
        
        self.exclusion_zones_btn = PushButton("Add Exclusion Zone")
        mid_layout.addWidget(self.exclusion_zones_btn)
        
        self.ez_collapsible = CollapsibleWidget("Exclusion Zones")
        mid_layout.addWidget(self.ez_collapsible)
        self.ez_list_layout = self.ez_collapsible.content_layout

        mid_layout.addStretch()
        
        main_layout.addWidget(self.mid_panel, 0)
        
        # RIGHT: Results Panel
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(10)
        
        results_header = QHBoxLayout()
        self.results_label = SubtitleLabel("Translation")
        self.results_label.setObjectName("engine_label")
        results_header.addWidget(self.results_label)
        
        results_header.addStretch()
        
        results_layout.addLayout(results_header)
        
        self.results_panel = ResultsPanel()
        self.results_panel.setObjectName("results_panel")
        results_layout.addWidget(self.results_panel)
        
        main_layout.addWidget(results_widget, 1)
        
        # ── Window Control Buttons (absolute top-right corner) ──
        self.minimize_btn = QtPushButton("—", self)
        self.minimize_btn.setFixedSize(32, 32)
        self.minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.minimize_btn.setStyleSheet("""
            QPushButton {
                background-color: #24283B;
                color: #7AA2F7;
                border: 1px solid #414868;
                border-radius: 6px;
                font-size: 18px;
                font-weight: bold;
                padding-bottom: 4px;
            }
            QPushButton:hover {
                background-color: #7AA2F7;
                color: white;
            }
        """)
        self.minimize_btn.clicked.connect(self.showMinimized)
        
        self.close_app_btn = QtPushButton("✕", self)
        self.close_app_btn.setFixedSize(32, 32)
        self.close_app_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #24283B;
                color: #F7768E;
                border: 1px solid #F7768E;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F7768E;
                color: white;
            }
        """)
        self.close_app_btn.clicked.connect(self.close)
        
        # Resize Grip
        self.sizegrip = QSizeGrip(self)
        self.sizegrip.setFixedSize(16, 16)
        
        self.refresh_areas_list()
        
        # Signals
        self.now_btn.clicked.connect(self.translate_now)
        self.clear_btn.clicked.connect(self.clear_translation)
        self.select_area_btn.clicked.connect(self.select_area)
        self.exclusion_zones_btn.clicked.connect(self.add_exclusion_zone)
        self.start_btn.clicked.connect(self.toggle_translation)
        
        self.start_btn.hotkey_changed.connect(lambda k: self.save_hotkey('start_btn', k))
        self.now_btn.hotkey_changed.connect(lambda k: self.save_hotkey('now_btn', k))
        self.clear_btn.hotkey_changed.connect(lambda k: self.save_hotkey('clear_btn', k))
        
        self.auto_update_chk.stateChanged.connect(self.save_settings)
        self.src_lang_combo.currentIndexChanged.connect(self.save_settings)
        self.target_lang_combo.currentIndexChanged.connect(self.save_settings)
        self.engine_combo.currentIndexChanged.connect(self.save_settings)
        self.ocr_engine_combo.currentIndexChanged.connect(self.save_settings)
        self.silent_mode_chk.stateChanged.connect(self.save_settings)
        self.aggregate_chk.stateChanged.connect(self.save_settings)
        self.retroarch_chk.stateChanged.connect(self.save_settings)
        self.tts_chk.stateChanged.connect(self.save_settings)
        self.interval_spin.valueChanged.connect(self.save_settings)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sizegrip.move(self.width() - self.sizegrip.width(), self.height() - self.sizegrip.height())
        self._position_window_buttons()
    
    def showEvent(self, event):
        super().showEvent(event)
        self._position_window_buttons()
    
    def _position_window_buttons(self):
        if hasattr(self, 'close_app_btn') and hasattr(self, 'minimize_btn'):
            m = 8
            # Position relative to the main window width
            self.close_app_btn.move(self.width() - 32 - m, m)
            self.minimize_btn.move(self.width() - 32 - m - 36, m)
            self.close_app_btn.raise_()
            self.minimize_btn.raise_()

    def save_hotkey(self, btn_name, keys):
        hotkeys = self.settings_manager.get('hotkeys', {})
        hotkeys[btn_name] = keys
        self.settings_manager.set('hotkeys', hotkeys)
        self.settings_manager.save()
        self.hotkey_manager.set_binding(btn_name, keys)
        
    def on_hotkey_triggered(self, btn_name):
        if btn_name == 'start_btn':
            self.toggle_translation()
        elif btn_name == 'now_btn':
            self.translate_now()
        elif btn_name == 'clear_btn':
            self.clear_translation()

    def change_ui_lang(self, index):
        self.current_lang = 'RU' if index == 0 else 'EN'
        self.update_ui_text()
        self.save_settings()

    def update_ui_text(self):
        old_loading = self.is_loading
        self.is_loading = True
        
        t = self.langs[self.current_lang]
        self.title_label.setText(t['title'])
        self.ui_lang_label.setText(t['lang_selection'])
        self.src_lang_label.setText(t['src_lang'])
        self.target_lang_label.setText(t['target_lang'])
        self.engine_label.setText(t['engine_label'])
        self.ocr_engine_label.setText(t.get('ocr_engine_label', 'OCR Engine'))
        self.results_label.setText(t['results_panel'])
        self.silent_mode_chk.setText(t['silent_mode'])
        self.aggregate_chk.setText(t['aggregate'])
        self.auto_update_chk.setText(t['auto_update'])
        self.interval_label.setText(t['interval_label'])
        self.now_btn.setText(t['translate_now'])
        self.clear_btn.setText(t['clear_btn'])
        self.theme_label.setText(t['theme_label'])
        self.opacity_label.setText(t['opacity_label'])
        self.pin_btn.setToolTip(t['pin_label'])
        
        # Localize language combos
        self.ui_lang_combo.blockSignals(True)
        self.ui_lang_combo.setCurrentIndex(0 if self.current_lang == 'RU' else 1)
        self.ui_lang_combo.blockSignals(False)
        
        self.src_lang_combo.blockSignals(True)
        self.target_lang_combo.blockSignals(True)
        self.src_lang_combo.clear()
        self.target_lang_combo.clear()
        
        for lang in self.SRC_LANGS:
            localized = t['languages'].get(lang, lang)
            self.src_lang_combo.addItem(localized)
        
        for lang in self.TGT_LANGS:
            localized = t['languages'].get(lang, lang)
            self.target_lang_combo.addItem(localized)
                
        # Restore selection after re-populating using mappings
        src_data = self.settings_manager.get('src_lang', 'English')
        try:
            idx_src = self.SRC_LANGS.index(src_data)
        except ValueError:
            idx_src = 1
        self.src_lang_combo.setCurrentIndex(idx_src)
        
        target_data = self.settings_manager.get('target_lang', 'Russian')
        try:
            idx_tgt = self.TGT_LANGS.index(target_data)
        except ValueError:
            idx_tgt = 0
        self.target_lang_combo.setCurrentIndex(idx_tgt)
        
        self.src_lang_combo.blockSignals(False)
        self.target_lang_combo.blockSignals(False)

        # Sync OCR Engine combo
        self.ocr_engine_combo.blockSignals(True)
        self.ocr_engine_combo.clear()
        self.ocr_engine_combo.addItem(t.get('ocr_easy_hint', "EasyOCR (пиксельные шрифты)"))
        
        from core.ocr import OCRManager
        has_tesseract = OCRManager().is_tesseract_installed()
        
        self.AVAILABLE_OCR_ENGINES = ["EasyOCR"]
        if has_tesseract:
            self.ocr_engine_combo.addItem("Tesseract (классический)")
            self.AVAILABLE_OCR_ENGINES.append("Tesseract")
            
        self.ocr_engine_combo.addItem("MultiOCR (комбинированный)")
        self.AVAILABLE_OCR_ENGINES.append("MultiOCR")
        
        # Restore selection after re-populating using mappings
        ocr_data = self.settings_manager.get('ocr_engine', 'EasyOCR')
        if ocr_data == "Tesseract" and not has_tesseract:
            ocr_data = "EasyOCR"
            
        try:
            idx_ocr = self.AVAILABLE_OCR_ENGINES.index(ocr_data)
        except ValueError:
            idx_ocr = 0  # EasyOCR
        self.ocr_engine_combo.setCurrentIndex(idx_ocr)
        self.ocr_engine_combo.blockSignals(False)
        

        areas_text = f"{t['select_area']} ({len(self.translation_areas)})"
        self.select_area_btn.setText(areas_text)
        self.areas_collapsible.setTitle(f"{t['areas_count']} ({len(self.translation_areas)})")
        
        ez_text = f"{t['exclusion_zones']} ({len(self.exclusion_zones)})"
        self.exclusion_zones_btn.setText(ez_text)
        self.ez_collapsible.setTitle(f"{t['exclusion_zones']} ({len(self.exclusion_zones)})")
        
        if not self.worker or not self.worker.isRunning():
            self.start_btn.setText(t['start_btn'])
        else:
            self.start_btn.setText(t['stop_btn'])
            
        self.refresh_areas_list()
        self.refresh_exclusion_zones_list()
        
        # Sync Overlay Indicators
        if self.translation_overlay:
            self.translation_overlay.set_active_areas(self.translation_areas, self.AREA_COLORS)
        
        self.is_loading = old_loading

    def setup_shadow(self, ):
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.main_container.setGraphicsEffect(shadow)

    def refresh_areas_list(self):
        # Clear existing
        while self.areas_list_layout.count():
            item = self.areas_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        t = LANGUAGES[self.current_lang]
        if not self.translation_areas:
            empty_lbl = BodyLabel(t['areas_list_empty'])
            empty_lbl.setStyleSheet("color: #565f89; font-style: italic; padding: 10px;")
            self.areas_list_layout.addWidget(empty_lbl)
            return

        for i, (area, enabled) in enumerate(zip(self.translation_areas, self.areas_enabled)):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 2, 5, 2)
            
            chk = CheckBox()
            chk.setChecked(enabled)
            chk.stateChanged.connect(lambda state, idx=i: self.toggle_area(idx, state))
            row_layout.addWidget(chk)
            
            color = self.AREA_COLORS[i % len(self.AREA_COLORS)]
            color_dot = QFrame()
            color_dot.setFixedSize(12, 12)
            color_dot.setStyleSheet(f"background-color: {color}; border-radius: 6px;")
            row_layout.addWidget(color_dot)
            
            name = BodyLabel(f"{t['area_label']} {i+1}")
            name.setStyleSheet("color: white; font-weight: bold;")
            row_layout.addWidget(name, 1)
            
            del_btn = PushButton(t['delete'])
            del_btn.setFixedSize(60, 24)
            del_btn.setStyleSheet("""
                QPushButton { background-color: #f7768e; color: white; border-radius: 4px; font-size: 10px; padding: 0; }
                QPushButton:hover { background-color: #ff5555; }
            """)
            del_btn.clicked.connect(lambda checked, idx=i: self.delete_area(idx))
            row_layout.addWidget(del_btn)
            
            self.areas_list_layout.addWidget(row)
        
        self.areas_list_layout.addStretch()

    def refresh_exclusion_zones_list(self):
        # Clear existing
        while self.ez_list_layout.count():
            item = self.ez_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        t = LANGUAGES[self.current_lang]
        if not self.exclusion_zones:
            empty_lbl = BodyLabel(t['exclusion_list_empty'])
            empty_lbl.setStyleSheet("color: #565f89; font-style: italic; padding: 0px 5px;")
            self.ez_list_layout.addWidget(empty_lbl, 0, Qt.AlignmentFlag.AlignTop)
            return

        for i, (zone, enabled) in enumerate(zip(self.exclusion_zones, self.exclusion_zones_enabled)):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 2, 5, 2)
            
            chk = CheckBox()
            chk.setChecked(enabled)
            chk.stateChanged.connect(lambda state, idx=i: self.toggle_exclusion_zone(idx, state))
            row_layout.addWidget(chk)
            
            name = BodyLabel(f"{t['exclusion_zone_label']} {i+1}")
            name.setStyleSheet("color: white; font-weight: bold;")
            row_layout.addWidget(name, 1)
            
            del_btn = PushButton(t['delete'])
            del_btn.setFixedSize(60, 24)
            del_btn.setStyleSheet("""
                QPushButton { background-color: #f7768e; color: white; border-radius: 4px; font-size: 10px; padding: 0; }
                QPushButton:hover { background-color: #ff5555; }
            """)
            del_btn.clicked.connect(lambda checked, idx=i: self.delete_exclusion_zone(idx))
            row_layout.addWidget(del_btn)
            
            self.ez_list_layout.addWidget(row)
            
        self.ez_list_layout.addStretch()

    def toggle_area(self, idx, state):
        self.areas_enabled[idx] = (state == 2)
        self.settings_manager.set('areas_enabled', self.areas_enabled)
        # Update overlay
        if self.translation_overlay:
            active = [self.translation_areas[i] for i, e in enumerate(self.areas_enabled) if e]
            colors = [self.AREA_COLORS[i % len(self.AREA_COLORS)] for i, e in enumerate(self.areas_enabled) if e]
            self.translation_overlay.set_active_areas(active, colors)

    def delete_area(self, idx):
        self.translation_areas.pop(idx)
        self.areas_enabled.pop(idx)
        self.settings_manager.set('translation_areas', [list(r.getRect()) for r in self.translation_areas])
        self.settings_manager.set('areas_enabled', self.areas_enabled)
        self.refresh_areas_list()
        self.update_ui_text()
        
        t = LANGUAGES[self.current_lang]
        # Update notification to reflect remaining areas count
        msg = t['area_deleted'].format(idx=idx+1) if 'area_deleted' in t else f"Area {idx+1} deleted."
        self.log_notification(msg)

        if self.translation_overlay:
            active = [self.translation_areas[i] for i, e in enumerate(self.areas_enabled) if e]
            colors = [self.AREA_COLORS[i % len(self.AREA_COLORS)] for i, e in enumerate(self.areas_enabled) if e]
            self.translation_overlay.set_active_areas(active, colors)

    def save_settings(self):
        if hasattr(self, 'is_loading') and self.is_loading:
            return
        s = self.settings_manager
        s.set('geometry', [self.x(), self.y(), self.width(), self.height()])
        
        # Save securely using array indices to prevent data corruption
        try:
            s.set('src_lang', self.SRC_LANGS[self.src_lang_combo.currentIndex()])
        except Exception: pass
        
        try:
            s.set('target_lang', self.TGT_LANGS[self.target_lang_combo.currentIndex()])
        except Exception: pass
        
        try:
            if hasattr(self, 'AVAILABLE_OCR_ENGINES'):
                s.set('ocr_engine', self.AVAILABLE_OCR_ENGINES[self.ocr_engine_combo.currentIndex()])
            else:
                s.set('ocr_engine', self.OCR_ENGINES[self.ocr_engine_combo.currentIndex()])
        except Exception: pass

        s.set('engine', self.engine_combo.currentText())
        s.set('interval', self.interval_spin.value())
        s.set('silent', self.silent_mode_chk.isChecked())
        s.set('aggregate', self.aggregate_chk.isChecked())
        if hasattr(self, 'retroarch_chk'):
            s.set('retroarch_pause', self.retroarch_chk.isChecked())
        if hasattr(self, 'tts_chk'):
            s.set('tts_enabled', self.tts_chk.isChecked())
        s.set('auto_update', self.auto_update_chk.isChecked())
        s.set('ui_lang', self.current_lang)
        s.set('theme', self.theme_combo.currentText())
        s.set('on_top', self.pin_btn.isChecked())
        s.set('opacity', self.opacity_slider.value())
        
        s.set('translation_areas', [[r.x(), r.y(), r.width(), r.height()] for r in self.translation_areas])
        s.set('areas_enabled', self.areas_enabled)
        s.save()
        
        # Force update worker with new settings
        if self.worker:
            self.worker.update_settings(s.data)
        s.set('exclusion_zones', [[r.x(), r.y(), r.width(), r.height()] for r in self.exclusion_zones])
        s.set('exclusion_zones_enabled', self.exclusion_zones_enabled)
        s.save()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    def select_area(self):
        from ui.area_selector import AreaSelector
        self.selector = AreaSelector()
        self.selector.area_selected.connect(self.on_area_selected)

    def add_exclusion_zone(self):
        from ui.area_selector import AreaSelector
        self.selector = AreaSelector()
        self.selector.area_selected.connect(self.on_exclusion_zone_selected)

    def on_area_selected(self, rect):
        self.translation_areas.append(rect)
        self.areas_enabled.append(True)
        self.refresh_areas_list()
        self.update_ui_text()
        
        t = self.langs[self.current_lang]
        msg = t['area_set'].format(idx=len(self.translation_areas))
        self.log_notification(msg)
        
        # Ensure overlay exists and show indicators immediately
        if not self.translation_overlay:
            from ui.overlay import TranslationOverlay
            self.translation_overlay = TranslationOverlay()
            from PyQt6.QtWidgets import QApplication
            self.translation_overlay.setGeometry(QApplication.primaryScreen().virtualGeometry())
            
        self.translation_overlay.set_active_areas(self.translation_areas, self.AREA_COLORS)
        self.save_settings()

    def toggle_exclusion_zone(self, idx, state):
        self.exclusion_zones_enabled[idx] = (state == 2)
        self.save_settings()

    def delete_exclusion_zone(self, idx):
        self.exclusion_zones.pop(idx)
        self.exclusion_zones_enabled.pop(idx)
        self.refresh_exclusion_zones_list()
        self.update_ui_text()
        self.save_settings()
        
        t = LANGUAGES[self.current_lang]
        msg = t.get('exclusion_deleted', 'Exclusion zone {idx} deleted.').format(idx=idx+1)
        self.log_notification(msg)

    def on_exclusion_zone_selected(self, rect):
        self.exclusion_zones.append(rect)
        self.exclusion_zones_enabled.append(True)
        self.refresh_exclusion_zones_list()
        self.update_ui_text()
        self.save_settings()
        t = LANGUAGES[self.current_lang]
        self.log_notification(t.get('exclusion_added', 'Exclusion zone added.'))

    def log_notification(self, message):
        self.results_panel.append_html(f"<b style='color: #BB9AF7;'>[!] {message}</b>")

    def force_set_focus(self, target_hwnd):
        import ctypes
        user32 = ctypes.windll.user32
        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd == target_hwnd:
            return
            
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, 0)
        target_thread = user32.GetWindowThreadProcessId(target_hwnd, 0)
        
        if fg_thread != target_thread:
            user32.AttachThreadInput(target_thread, fg_thread, True)
            
        user32.SetForegroundWindow(target_hwnd)
        user32.SetFocus(target_hwnd)
        
        if fg_thread != target_thread:
            user32.AttachThreadInput(target_thread, fg_thread, False)

    def clear_translation(self):
        if getattr(self, 'last_game_hwnd', None) and self.retroarch_chk.isChecked():
            # Возвращаем фокус игре
            self.force_set_focus(self.last_game_hwnd)
            self.last_game_hwnd = None
            
        if self.translation_overlay:
            self.translation_overlay.set_translations([])
            
    def translate_now(self):
        if self.retroarch_chk.isChecked():
            import ctypes
            fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
            if fg_hwnd and fg_hwnd != int(self.winId()) and fg_hwnd != int(self.dummy_focus_widget.winId()):
                if self.translation_overlay and fg_hwnd == int(self.translation_overlay.winId()):
                    pass
                else:
                    self.last_game_hwnd = fg_hwnd
            
            # Переключаем фокус на программу для паузы игры (используем AttachThreadInput для обхода защиты Windows)
            self.force_set_focus(int(self.dummy_focus_widget.winId()))

        if not self.translation_areas:
            self.select_area()
            return
            
        self.clear_translation()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
            
        if self.worker and self.worker.isRunning():
            self.worker.trigger_manual()
        else:
            t = LANGUAGES[self.current_lang]
            self.log_notification(t.get('one_time_translate', "One-time translate..."))
            # Ensure overlay sees the areas immediately
            if self.translation_overlay:
                self.translation_overlay.set_active_areas(self.translation_areas, self.AREA_COLORS)
            self.start_translation(manual_once=True)

    def toggle_translation(self):
        if self.worker and self.worker.isRunning():
            self.stop_translation()
        else:
            self.start_translation()

    def start_translation(self, manual_once=False):
        if not self.translation_areas:
            self.select_area()
            return
            
        from core.worker import TranslatorWorker
        from ui.overlay import TranslationOverlay
        
        # Mapping for languages
        lang_map = {
            'Russian': 'ru', 'English': 'en', 'Japanese': 'ja', 
            'Chinese': 'zh-CN', 'Korean': 'ko', 'German': 'de', 'French': 'fr',
            'Auto': 'auto'
        }
        
        settings = {
            'areas': [self.translation_areas[i] for i, e in enumerate(self.areas_enabled) if e],
            'exclusion_zones': [self.exclusion_zones[i] for i, e in enumerate(self.exclusion_zones_enabled) if e],
            'engine': self.engine_combo.currentText(),
            'aggregate': self.aggregate_chk.isChecked(),
            'silent': self.silent_mode_chk.isChecked(),
            'tts_enabled': getattr(self, 'tts_chk', None) and self.tts_chk.isChecked(),
            'src_lang': lang_map.get(self.src_lang_combo.currentText(), 'auto'),
            'target_lang': lang_map.get(self.target_lang_combo.currentText(), 'ru'),
            'interval': self.interval_spin.value(),
            'manual_once': manual_once,
            'exclusion_zones': self.exclusion_zones,
            'exclusion_zones_enabled': self.exclusion_zones_enabled
        }
        
        if not self.translation_overlay:
            self.translation_overlay = TranslationOverlay()
            from PyQt6.QtWidgets import QApplication
            self.translation_overlay.setGeometry(QApplication.primaryScreen().virtualGeometry())
        
        self.translation_overlay.set_active_areas(self.translation_areas, self.AREA_COLORS)
        
        self.worker = TranslatorWorker(settings)
        self.worker.new_translation.connect(self.handle_translation)
        
        if manual_once:
            self.worker.start()
            # New worker needs a kick to start processing
            # We delay slightly to let the loop start, or rely on thread-safety
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self.worker.trigger_manual)
            # We don't change Button text or Start Permanent cycle
        else:
            self.worker.start()
            self.start_btn.setText(self.langs[self.current_lang]['stop_btn'])
            self.start_btn.setStyleSheet("background: #F7768E; color: white;")
        
        self.save_settings()

    def handle_translation(self, data):
        if not self.translation_overlay:
            return

        t = self.langs[self.current_lang]
        
        # 1. Update Overlay
        if self.translation_overlay:
            if not self.translation_overlay.isVisible():
                self.translation_overlay.show()
                self.translation_overlay.raise_()
            
            if self.silent_mode_chk.isChecked():
                self.translation_overlay.set_translations(data)
            else:
                self.translation_overlay.set_translations([]) # Clear text, keep indicators
            
            # 2. Update Side Panel
            # ALWAYS clear if we received something (even empty) to remove "One-time translate..."
            self.results_panel.clear()
            
            if not data:
                # Provide feedback if nothing was found
                no_text_msg = t.get('no_text_found', "No text found")
                self.results_panel.append_html(f"<i style='color: #565f89;'>{no_text_msg}</i>")
                return
            
            # ── 3. Text-to-Speech (TTS) ──
            if hasattr(self, 'tts_chk') and self.tts_chk.isChecked():
                full_text = " ".join([b.get('text', '') for item in data for b in item.get('blocks', []) if b.get('text')]).strip()
                if full_text and full_text != getattr(self, 'last_tts_text', ''):
                    self.last_tts_text = full_text
                    import threading
                    def run_tts(txt):
                        try:
                            import pyttsx3
                            engine = pyttsx3.init()
                            for v in engine.getProperty('voices'):
                                if 'ru' in getattr(v, 'languages', []) or 'russian' in v.name.lower():
                                    engine.setProperty('voice', v.id)
                                    break
                            engine.say(txt)
                            engine.runAndWait()
                        except Exception as e:
                            print(f"TTS Error: {e}")
                    threading.Thread(target=run_tts, args=(full_text,), daemon=True).start()
            
            # Sort by Y position (top to bottom), then by X (left to right)
            sorted_data = sorted(data, key=lambda x: (x['rect'].y(), x['rect'].x()))
            
            # Group by area_index
            from collections import defaultdict
            grouped = defaultdict(list)
            for item in sorted_data:
                grouped[item.get('area_index', 1)].append(item)
            
            # Sort indices to draw in order
            indices = sorted(grouped.keys())
            
            for idx in indices:
                color = self.AREA_COLORS[(idx-1) % len(self.AREA_COLORS)]
                
                # Get engine from first block
                first_item_blocks = grouped[idx][0].get('blocks', [])
                engine_name = first_item_blocks[0].get('engine', 'Google') if first_item_blocks else 'Google'
                
                area_label = t['area_header'].format(idx=idx, engine=engine_name)
                
                # ── Build Professional HTML ──
                content_html = f"""<div style='font-family: "Segoe UI", sans-serif; padding: 0; margin: 0;'>"""
                
                # Area header line (tiny, subtle)
                content_html += f"""
                <div style='margin-bottom: 10px; padding-bottom: 5px; border-bottom: 1px solid rgba(255,255,255,0.06);'>
                    <span style='color: {color}; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;'>{area_label}</span>
                    <span style='color: #414868; font-size: 9px; margin-left: 8px;'>{engine_name}</span>
                </div>"""
                
                # ── Flatten and merge blocks: name-only → attach to next text block ──
                all_blocks = []
                for item in grouped[idx]:
                    for block in item.get('blocks', []):
                        all_blocks.append(block)
                
                # Merge: if a block has name but no text, attach name to next block
                merged_blocks = []
                pending_name = None
                for block in all_blocks:
                    name = block.get('name')
                    text = block.get('text', '').strip()
                    
                    if name and not text:
                        # Name-only block — save for next
                        pending_name = name
                    elif text:
                        final_name = pending_name or name
                        pending_name = None
                        merged_blocks.append({'name': final_name, 'text': text})
                    elif name and text:
                        pending_name = None
                        merged_blocks.append({'name': name, 'text': text})
                
                # If only a name remains (no text followed), still show it
                if pending_name:
                    merged_blocks.append({'name': pending_name, 'text': ''})
                
                for mb in merged_blocks:
                    name = mb.get('name')
                    text = mb.get('text', '')
                    
                    # Skip empty
                    if not name and not text:
                        continue
                        
                    # ── Name Badge (if present) ──
                    if name:
                        content_html += f"""
                        <div style='margin-bottom: 4px; margin-top: 6px;'>
                            <span style='
                                display: inline-block;
                                background: linear-gradient(135deg, rgba(122,162,247,0.2), rgba(187,154,247,0.15));
                                color: #7AA2F7;
                                padding: 3px 10px;
                                border-radius: 10px;
                                font-weight: 700;
                                font-size: 11px;
                                text-transform: uppercase;
                                letter-spacing: 0.8px;
                                border: 1px solid rgba(122,162,247,0.25);
                            '>{name}</span>
                        </div>"""
                    
                    # ── Translation Text ──
                    if text:
                        content_html += f"""
                        <div style='
                            color: #c0caf5;
                            font-size: 14px;
                            line-height: 1.65;
                            margin-bottom: 8px;
                            padding-left: 2px;
                        '>{text}</div>"""
                
                content_html += "</div>"
                
                # Append animated native card
                self.results_panel.append_card(content_html, color)

    def stop_translation(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        if self.translation_overlay:
            self.translation_overlay.close()
            self.translation_overlay = None
        self.start_btn.setText(self.langs[self.current_lang]['start_btn'])
        self.start_btn.setObjectName("action_btn")
        self.setStyleSheet(self.styleSheet()) # Refresh styles
        self.setup_shadow()

    # Mouse events for window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def apply_theme(self, theme_name):
        if theme_name not in THEMES:
            return
            
        theme = THEMES[theme_name]
        
        # Base QSS
        qss = f"""
            *:focus {{
                outline: none;
                border: none;
            }}
            QMainWindow {{ background: transparent; }}
            #main_container {{
                background-color: {theme['bg']};
                border-radius: 12px;
                border: 1px solid {theme['input_border']};
            }}
            QWidget {{
                color: {theme['fg']};
                font-family: 'Segoe UI', sans-serif;
            }}
            QLabel {{
                color: {theme['fg']};
            }}
            QLabel#title {{
                color: {theme['fg']};
                font-size: 18px;
                font-weight: bold;
            }}
            QComboBox {{
                background-color: {theme['input_bg']};
                color: {theme['input_fg']};
                border: 1px solid {theme['input_border']};
                border-radius: 4px;
                padding: 5px;
            }}
            QComboBox::drop-down {{
                border: 0px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme['input_bg']};
                color: {theme['input_fg']};
                selection-background-color: {theme['btn_bg']};
            }}
            QPushButton {{
                background-color: {theme['btn_bg']};
                color: {theme['btn_fg']};
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['input_border']};
            }}
            QPushButton#action_btn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #BB9AF7, stop:1 #7AA2F7);
                color: white;
                font-size: 14px;
            }}
            #secondary_btn {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['input_border']};
            }}
            QCheckBox {{
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {theme['input_border']};
                background-color: {theme['input_bg']};
            }}
            QCheckBox::indicator:checked {{
                background-color: #27ae60;
                border: 1px solid #27ae60;
            }}
            QDoubleSpinBox {{
                background-color: {theme['input_bg']};
                color: {theme['input_fg']};
                border: 1px solid {theme['input_border']};
                padding: 5px;
                border-radius: 4px;
            }}
            QPushButton#now_btn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #27ae60, stop:1 #2ecc71);
                color: white;
                font-size: 14px;
                border: none;
            }}
            QPushButton#now_btn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2ecc71, stop:1 #27ae60);
            }}
            QPushButton#clear_btn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff0000, stop:1 #cc0000);
                color: white;
                border: none;
                font-size: 14px;
            }}
            QPushButton#clear_btn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #cc0000, stop:1 #ff0000);
            }}
            QPushButton#pin_btn {{
                background-color: {theme['btn_bg'] if not self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint else '#27ae60'};
                border-radius: 4px;
                padding: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #7AA2F7;
                border: 1px solid {theme['input_border']};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {theme['input_border']};
                height: 4px;
                background: {theme['input_bg']};
                margin: 2px 0;
            }}
        """
        self.setStyleSheet(qss)
        self.save_settings()

    def toggle_pin(self, checked):
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show() # Necessary after flag change
        self.apply_theme(self.theme_combo.currentText()) # Refresh pin button color

    def change_opacity(self, value):
        self.setWindowOpacity(value / 100.0)
        if hasattr(self, 'opacity_value_label'):
            self.opacity_value_label.setText(f"{value}%")
