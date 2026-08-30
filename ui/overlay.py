from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect, QPoint, QRectF
from PyQt6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen, 
                         QFontMetrics, QLinearGradient, QBrush)

class TranslationOverlay(QWidget):
    """
    Silent Mode Overlay — draws translated text directly over the game,
    covering original text blocks with matching background and readable text.
    Each paragraph gets its own overlay block at the exact position.
    """
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool | 
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        self.translations = []
        self.active_areas = []
        self.area_colors = []
        
        self.protect_from_capture()
        self.show()

    def protect_from_capture(self):
        """Intentionally disabled: user needs to screenshot overlay text."""
        pass

    def set_active_areas(self, areas, colors):
        self.active_areas = areas
        self.area_colors = colors
        self.update()
        self.raise_()

    def set_translations(self, data):
        self.translations = data
        self.update()
        
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        self.setWindowOpacity(0.0)
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(250)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        origin = self.geometry().topLeft()
        
        # ── 1. Draw Active Area Borders (subtle dashed) ──
        # Показываем технические рамки только если нет активного перевода
        if not self.translations:
            for i, rect in enumerate(self.active_areas):
                color_hex = self.area_colors[i % len(self.area_colors)]
                color = QColor(color_hex)
                local_rect = rect.translated(-origin)
                
                painter.setOpacity(0.3)
                pen = QPen(color, 1.5, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(local_rect)
                
                # Small badge
                painter.setOpacity(0.7)
                badge_font = QFont("Segoe UI", 8)
                badge_font.setBold(True)
                painter.setFont(badge_font)
                badge_rect = QRectF(local_rect.x() + 2, local_rect.y() + 2, 16, 16)
                painter.setBrush(QBrush(QColor(color_hex)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(badge_rect, 3, 3)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        
        painter.setOpacity(1.0)
        
        # ── 2. Draw Translation Blocks ──
        for item in self.translations:
            blocks = item.get('blocks', [])
            if not blocks:
                continue
                
            bg_color = item.get('bg_color', QColor(0, 0, 0)) # Default to black for better blending
            area_rect = item.get('area_rect')
            if not area_rect:
                continue
            area_local = area_rect.translated(-origin)
            
            for mb in blocks:
                text = mb.get('text', '')
                name = mb.get('name')
                block_rect = mb.get('rect')
                
                # Build display text
                if name and text:
                    display = f"{name}: {text}"
                elif name:
                    display = name
                elif text:
                    display = text
                else:
                    continue
                
                # ── Position: use block rect if available, else area rect ──
                if block_rect:
                    local_r = QRectF(block_rect.translated(-origin))
                else:
                    local_r = QRectF(area_local)
                
                # ── Font sizing: estimate single line height ──
                line_h = mb.get('line_height', 0)
                if line_h <= 0:
                    orig_h = max(local_r.height(), 16)
                    estimated_lines = max(1, round(orig_h / 22)) 
                    line_h = orig_h / estimated_lines
                font_px = max(int(line_h * 0.95), 14) # Увеличил коэффициент до 0.95 для идеального совпадения по высоте
                font_px = min(font_px, 42)
                
                font = QFont("Georgia", 1) # Шрифт с засечками, похожий на оригинал
                font.setPixelSize(font_px)
                font.setItalic(True) # Делаем курсив, как на скриншоте
                font.setWeight(QFont.Weight.Medium)
                font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
                
                # ── Build display lines ──
                lines = []
                if name:
                    lines.append(('name', name))
                if text:
                    lines.append(('text', text))
                
                if not lines:
                    continue
                
                # ── Measure total content height ──
                # Расширяем доступную ширину до границ зоны выделения (чтобы длинный русский текст не переносился зря)
                render_w = int(area_local.width() - (local_r.x() - area_local.x()) - 8)
                # Убеждаемся, что ширина не меньше оригинального текста, но не больше 1.5x оригинала 
                # Allow 30% horizontal expansion so menu items don't wrap immediately
                render_w = int(local_r.width() * 1.3)
                render_w = max(render_w, 50)
                
                # ── Ensure render_w is wide enough for the longest word ──
                fm_init = QFontMetrics(font)
                max_word_w = 0
                for kind, content in lines:
                    if kind != 'name':
                        for word in content.split():
                            ww = fm_init.horizontalAdvance(word)
                            if ww > max_word_w:
                                max_word_w = ww
                
                if max_word_w + 10 > render_w:
                    render_w = max_word_w + 10
                
                # ── Screen boundary checking ──
                max_w = self.width() - local_r.x() - 12
                if render_w > max_w:
                    render_w = max_w
                
                # ── Auto-shrink font to fit vertical space ──
                max_allowed_h = local_r.height() * 1.5 + 10
                
                while font_px > 10:
                    font.setPixelSize(font_px)
                    fm = QFontMetrics(font)
                    
                    name_font = QFont("Georgia", 1)
                    name_font.setPixelSize(max(font_px - 2, 9))
                    name_font.setWeight(QFont.Weight.Bold)
                    name_font.setItalic(True)
                    name_fm = QFontMetrics(name_font)
                    
                    total_h = 0
                    for kind, content in lines:
                        if kind == 'name':
                            br = name_fm.boundingRect(QRect(0, 0, render_w - 4, 500), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                            total_h += br.height() + 14
                        else:
                            br = fm.boundingRect(QRect(0, 0, render_w - 4, 500), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                            total_h += br.height() + 4
                            
                    if total_h <= max_allowed_h:
                        break
                    font_px -= 1
                    
                line_rects = []
                for kind, content in lines:
                    if kind == 'name':
                        br = name_fm.boundingRect(QRect(0, 0, render_w - 4, 500), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                        line_rects.append((kind, content, br.height() + 2))
                    else:
                        br = fm.boundingRect(QRect(0, 0, render_w - 4, 500), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                        line_rects.append((kind, content, br.height()))
                
                draw_x = local_r.x()
                draw_y = local_r.y()
                
                block_bg = mb.get('bg_color', bg_color)
                r, g, b = block_bg.red(), block_bg.green(), block_bg.blue()
                
                painter.setOpacity(1.0)
                painter.setPen(Qt.PenStyle.NoPen)
                
                cursor_y = int(draw_y)
                
                for kind, content, h in line_rects:
                    if kind == 'name':
                        painter.setFont(name_font)
                        name_color = QColor(255, 230, 150) # Золотистый/желтый цвет для имен
                        
                        # Вычисляем точную ширину имени, чтобы рамка не растягивалась
                        br = name_fm.boundingRect(QRect(0, 0, 1000, 500), Qt.AlignmentFlag.AlignLeft, content)
                        name_w = min(br.width() + 16, render_w + 12)
                        
                        bg_rect = QRectF(draw_x - 6, cursor_y - 6, name_w, h + 10)
                        
                        # Отрисовка отдельного небольшого окна для имени (как в японских RPG)
                        painter.setBrush(QColor(r, g, b, 245))
                        painter.drawRoundedRect(bg_rect, 6, 6)
                        
                        # Светлая рамка для окошка имени
                        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
                        painter.drawRoundedRect(bg_rect, 6, 6)
                        painter.setPen(Qt.PenStyle.NoPen)
                        
                        tr = QRect(int(draw_x) + 2, cursor_y, int(name_w), h + 2)
                        
                        # Тень текста имени
                        painter.setPen(QColor(0, 0, 0, 180))
                        painter.drawText(tr.translated(1, 1), Qt.AlignmentFlag.AlignLeft, content)
                        
                        # Основной текст имени
                        painter.setPen(name_color)
                        painter.drawText(tr, Qt.AlignmentFlag.AlignLeft, content)
                        
                        cursor_y += h + 14 # Отступ между окном имени и окном диалога
                    else:
                        # Окно основного диалога
                        # Убеждаемся, что фон полностью закрывает оригинальный текст снизу
                        required_h = (draw_y + local_r.height()) - cursor_y
                        bg_h = max(h, required_h)
                            
                        bg_rect = QRectF(draw_x - 6, cursor_y - 4, render_w + 12, bg_h + 8)
                        
                        painter.setBrush(QColor(r, g, b, 255))
                        painter.drawRoundedRect(bg_rect, 8, 8)
                        
                        painter.setFont(font)
                        tr = QRect(int(draw_x) + 2, cursor_y, render_w, h + 4)
                        
                        text_color = mb.get('text_color', QColor(245, 245, 245))
                        
                        painter.setPen(QColor(0, 0, 0, 180))
                        painter.drawText(tr.translated(1, 1), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                        painter.drawText(tr.translated(2, 2), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                        
                        painter.setPen(text_color)
                        painter.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, content)
                        
                        cursor_y += bg_h + 4

    def clear(self):
        self.translations = []
        self.update()
