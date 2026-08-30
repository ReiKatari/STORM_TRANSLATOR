import asyncio
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, QRect
from PyQt6.QtGui import QColor
from core.capture import ScreenCapturer
from core.ocr import OCRManager
from core.translator import TranslationManager

class TranslatorWorker(QThread):
    new_translation = pyqtSignal(list)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.running = True
        self.ocr = OCRManager()
        self.translator = TranslationManager()
        self.loop = asyncio.new_event_loop()
        self.manual_trigger = asyncio.Event()

    def stop(self):
        self.running = False
        self.manual_trigger.set()

    def trigger_manual(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.manual_trigger.set)
        else:
            print("DEBUG: Loop not running, scheduling manual trigger...")
            # If loop hasn't started, we can't use call_soon_threadsafe easily without risks 
            # if the loop isn't the current thread's loop.
            # But since we just started the thread, we can rely on the fact that
            # main_loop will wait() on the event.
            # If we set it here (different thread), is it safe?
            # Creating a task to set it might be safer if loop object exists.
            pass
            
    def run(self):
        print("DEBUG: Worker Thread Started")
        asyncio.set_event_loop(self.loop)
        # Pre-set trigger if we are in manual_only mode and it was requested before loop start?
        # Actually, simpler: pass a flag to run() or main_loop()
        self.loop.run_until_complete(self.main_loop())

    def update_settings(self, new_settings):
        # Preserve manual_once flag as it is a runtime-only setting
        current_manual = self.settings.get('manual_once')
        self.settings = new_settings.copy()
        if current_manual is not None:
            self.settings['manual_once'] = current_manual
            
        # Reconstruct 'areas' and 'exclusion_zones' as QRect objects from raw data
        # SettingsManager stores them as [x, y, w, h], but worker needs QRect
        t_areas = self.settings.get('translation_areas', [])
        enabled = self.settings.get('areas_enabled', [])
        active_areas = []
        for i, rect_data in enumerate(t_areas):
             if i < len(enabled) and enabled[i]:
                 active_areas.append(QRect(*rect_data))
        self.settings['areas'] = active_areas

        ez_data = self.settings.get('exclusion_zones', [])
        ez_enabled = self.settings.get('exclusion_zones_enabled', [])
        active_ez = []
        for i, rect_data in enumerate(ez_data):
             if i < len(ez_enabled) and ez_enabled[i]:
                 active_ez.append(QRect(*rect_data))
        self.settings['exclusion_zones'] = active_ez

    def clean_text(self, text):
        import re
        t = re.sub(r'[\r\n\t]', ' ', str(text)).strip()
        # Common OCR fixes for this game's font
        # Handle 'Nlfador', 'NIfador', 'Hlfador', 'Altfador' etc.
        t = re.sub(r'(?i)\b[A-Za-z]{1,3}fador\b', 'Alfador', t)
        
        # Remove sequences of 3+ identical special chars (likely OCR noise)
        t = re.sub(r'([^\w\s])\1{2,}', '', t)
        # Replace misread OCR chars common in pixel games
        t = t.replace('|', 'I').replace('[', '(').replace(']', ')')
        # Clean up weird punctuation artifacts at edges
        t = t.replace(';.', '.').replace('.,', '.').replace(',.', '.')
        
        # Specific pixel-font hallucinations (English context)
        t = re.sub(r'\bt0\b', 'to', t)
        t = re.sub(r'\byov\b', 'you', t)
        t = re.sub(r'\bYov\b', 'You', t)
        t = re.sub(r'\bMurry\b', 'Hurry', t)
        t = re.sub(r'\bmurry\b', 'hurry', t)
        t = re.sub(r'\bGiri\b', 'Girl', t)
        t = re.sub(r'\bgiri\b', 'girl', t)
        
        # Semicolons are rarely terminal punctuation in dialog; often a misread dot
        t = re.sub(r';$', '.', t.strip())
        
        return t.strip()
    
    def is_garbage(self, text):
        """
        Smart garbage detector for RPG game OCR output.
        Returns True if the text is noise (stats, HUD, garbled OCR).
        """
        import re
        if len(text) < 2:
            return True
        
        # Count character types
        letters = sum(c.isalpha() for c in text)
        digits = sum(c.isdigit() for c in text)
        specials = sum(not c.isalnum() and not c.isspace() for c in text)
        total = len(text.replace(' ', ''))
        
        if total == 0:
            return True
        
        # 1. High special character ratio → garbage (e.g. "FE= 'Fisbter 0 43= ~C2CA7")
        if specials / total > 0.25 and total > 5:
            return True
            
        # 2. More digits+specials than letters → stat bar (e.g. "10% MP10 MPO N23 D20")
        if (digits + specials) > letters and total > 4:
            return True
            
        # 3. Hex-like sequences (e.g. "C2CA7", "761C", "7371")
        hex_matches = re.findall(r'\b[0-9A-Fa-f]{3,}\b', text)
        if len(hex_matches) >= 2:
            return True
            
        # 4. RPG stat keywords with numbers nearby
        stat_patterns = [
            r'\bHP\s*\d', r'\bMP\s*\d', r'\bLV\s*\d', r'\bEXP\s*\d',
            r'\bATK\s*\d', r'\bDEF\s*\d', r'\bSTR\s*\d', r'\bDEX\s*\d',
            r'\bD\d{1,2}\b', r'\bLUX\b', r'\bMPO\b', r'\bNPO\b'
        ]
        for pat in stat_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
                
        # 5. Too many short "words" with digits mixed in (e.g. "MP10 N23 D20 7371")
        words = text.split()
        noise_words = 0
        for w in words:
            has_digit = any(c.isdigit() for c in w)
            has_letter = any(c.isalpha() for c in w)
            has_special = any(not c.isalnum() for c in w)
            if (has_digit and has_letter and len(w) <= 5) or has_special:
                noise_words += 1
        if len(words) > 2 and noise_words / len(words) > 0.5:
            return True
            
        # 6. Average word length too short for meaningful text (e.g. "FE MP D20 C 783")
        if len(words) > 3:
            avg_len = sum(len(w) for w in words) / len(words)
            if avg_len < 2.5:
                return True
        
        # 7. Isolated very short text (1 word, ≤5 chars, all lowercase) — likely HUD noise
        if len(words) == 1 and len(text) <= 5 and text.islower():
            return True
        
        # 8. Contains ≥2 standalone number tokens → HUD/stats (e.g. "Sabra Fighter 14 023")
        standalone_nums = [w for w in words if w.isdigit()]
        if len(standalone_nums) >= 2:
            return True
        
        # 9. Mix of name + numbers at end (e.g. "Sabra Fighter 14 023")
        if len(words) >= 3 and words[-1].isdigit():
            return True
        
        return False

    def run(self):
        self.capturer = ScreenCapturer() # Initialize in the worker thread
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main_loop())

    async def main_loop(self):
        print(f"DEBUG: main_loop started. manual_once={self.settings.get('manual_once')}")
        win_lang_map = {
            'English': 'en-US',
            'Russian': 'ru-RU',
            'Japanese': 'ja-JP',
            'Chinese': 'zh-CN',
            'Korean': 'ko-KR',
            'German': 'de-DE',
            'French': 'fr-FR',
            'French': 'fr-FR',
            'Auto': 'en-US'
        }
        
        trans_lang_map = {
            'English': 'en',
            'Russian': 'ru',
            'Japanese': 'ja',
            'Chinese': 'zh-CN',
            'Korean': 'ko',
            'German': 'de',
            'French': 'fr',
            'Auto': 'auto'
        }
        
        while self.running:
            areas = self.settings.get('areas', [])
            if not areas:
                await asyncio.sleep(1)
                continue

            try:
                if not self.settings.get('manual_once', False):
                    # Normal mode: wait for interval or manual trigger
                    try:
                        await asyncio.wait_for(self.manual_trigger.wait(), timeout=self.settings.get('interval', 1.0))
                        self.manual_trigger.clear()
                    except asyncio.TimeoutError:
                        pass # Valid timeout, proceed
                else:
                    # Manual only mode: wait strictly for trigger
                    print("DEBUG: Waiting for manual trigger...")
                    await self.manual_trigger.wait()
                    print("DEBUG: Manual trigger received!")
                    self.manual_trigger.clear()
                    await asyncio.sleep(0.15) # Wait for UI to hide before screenshot
            except Exception as e:
                print(f"Error in wait: {e}")

            all_translations = []
            src_lang_name = self.settings.get('src_lang', 'Auto')
            win_lang_code = win_lang_map.get(src_lang_name, 'en-US')
            
            # RetroArch Auto-Pause (Only trigger once per manual cycle)
            if self.settings.get('retroarch_pause', False) and self.settings.get('manual_once', False):
                try:
                    from core.retroarch import RetroArchClient
                    RetroArchClient().pause_toggle()
                except Exception as e:
                    print(f"DEBUG: Failed to import/run RetroArchClient: {e}")
            
            for idx, area in enumerate(areas):
                # 1. Capture Area
                img = self.capturer.capture_area(area.x(), area.y(), area.width(), area.height())
                img_np = np.array(img)
                
                # Auto-hide translation if screen changed drastically (e.g. running around)
                if not hasattr(self, 'prev_frames'):
                    self.prev_frames = {}
                
                if idx in self.prev_frames and self.prev_frames[idx].shape == img_np.shape:
                    # Calculate Mean Absolute Difference
                    diff = np.mean(np.abs(img_np.astype(float) - self.prev_frames[idx].astype(float)))
                    if diff > 40.0 and not self.settings.get('manual_once'):
                        # Instantly clear overlay while we process new frame
                        self.new_translation.emit([])
                
                self.prev_frames[idx] = img_np.copy()
                
                # Apply exclusion zones
                exclusion_zones = self.settings.get('exclusion_zones', [])
                exclusion_zones_enabled = self.settings.get('exclusion_zones_enabled', [])
                
                for idx_ez, zone in enumerate(exclusion_zones):
                    if idx_ez < len(exclusion_zones_enabled) and not exclusion_zones_enabled[idx_ez]:
                        continue
                        
                    local_left = zone.x() - area.x()
                    local_top = zone.y() - area.y()
                    local_right = zone.right() - area.x() + 1 # QRect.right() is x + width - 1
                    local_bottom = zone.bottom() - area.y() + 1
                    
                    lx = max(0, local_left)
                    ly = max(0, local_top)
                    rx = min(area.width(), local_right)
                    ry = min(area.height(), local_bottom)
                    
                    if rx > lx and ry > ly:
                        img_np[ly:ry, lx:rx] = 0
                
                from PIL import Image
                img_pil = Image.fromarray(img_np)
                
                # Sample background color from captured area for silent mode overlay
                try:
                    # Use median color of the entire area to robustly find the background color,
                    # completely ignoring character portraits on the left or text on the right.
                    if len(img_np.shape) == 3:
                        med_color = np.median(img_np, axis=(0, 1)).astype(int)
                        area_bg_color = QColor(int(med_color[0]), int(med_color[1]), int(med_color[2]))
                    else:
                        med_val = int(np.median(img_np))
                        area_bg_color = QColor(med_val, med_val, med_val)
                except Exception:
                    area_bg_color = QColor(20, 20, 50)
                
                # Production mode: capture remains entirely in-memory

                # 2. OCR
                ocr_engine = self.settings.get('ocr_engine', 'Windows')
                ocr_results = await self.ocr.recognize(img_pil, lang_code=win_lang_code, engine=ocr_engine)
                if not ocr_results:
                    print(f"DEBUG: OCR result empty for area {idx+1}")
                    continue
                
                # 3. Grouping Lines (Merging sentences/paragraphs)
                for res in ocr_results:
                    res['cy'] = res['rect']['y'] + res['rect']['height'] / 2.0
                
                ocr_results.sort(key=lambda x: x['cy'])
                lines_grouped = []
                if ocr_results:
                    curr_line = [ocr_results[0]]
                    line_cy = ocr_results[0]['cy']
                    for i in range(1, len(ocr_results)):
                        curr = ocr_results[i]
                        avg_h = (curr_line[0]['rect']['height'] + curr['rect']['height']) / 2.0
                        if abs(curr['cy'] - line_cy) < avg_h * 0.6:
                            curr_line.append(curr)
                            line_cy = sum(x['cy'] for x in curr_line) / len(curr_line)
                        else:
                            curr_line.sort(key=lambda x: x['rect']['x'])
                            lines_grouped.extend(curr_line)
                            curr_line = [curr]
                            line_cy = curr['cy']
                    curr_line.sort(key=lambda x: x['rect']['x'])
                    lines_grouped.extend(curr_line)
                ocr_results = lines_grouped
                
                groups = []
                if ocr_results:
                    current_group = [ocr_results[0]]
                    for i in range(1, len(ocr_results)):
                        prev = ocr_results[i-1]
                        curr = ocr_results[i]
                        
                        y_diff = curr['rect']['y'] - (prev['rect']['y'] + prev['rect']['height'])
                        x_dist = abs(curr['rect']['x'] - prev['rect']['x'])
                        y_overlap = (curr['rect']['y'] < prev['rect']['y'] + prev['rect']['height']) and \
                                   (curr['rect']['y'] + curr['rect']['height'] > prev['rect']['y'])
                        
                        is_same_paragraph = False
                        if y_diff < prev['rect']['height'] * 10.0: 
                            is_same_paragraph = True
                        elif y_overlap and x_dist < prev['rect']['height'] * 4.0:
                            is_same_paragraph = True
                            
                        if is_same_paragraph:
                            current_group.append(curr)
                        else:
                            groups.append(current_group)
                            current_group = [curr]
                    groups.append(current_group)
                
                # 4. Translate Blocks
                engine = 'AGGREGATION' if self.settings.get('aggregate') else self.settings.get('engine', 'Google')
                raw_src = self.settings.get('src_lang', 'Auto')
                raw_tgt = self.settings.get('target_lang', 'Russian')
                src_lang = trans_lang_map.get(raw_src, 'auto')
                target_lang = trans_lang_map.get(raw_tgt, 'ru')
                for g_idx, group in enumerate(groups):
                    # Group into visual paragraphs
                    paragraphs = []
                    current_para = [group[0]]
                    for i in range(1, len(group)):
                        prev = group[i-1]
                        curr = group[i]
                        gap = curr['rect']['y'] - (prev['rect']['y'] + prev['rect']['height'])
                        avg_h = (prev['rect']['height'] + curr['rect']['height']) / 2.0
                        txt = self.clean_text(curr['text'])
                        
                        # Если они на одной строке (по Y), проверяем X-расстояние
                        x_gap = 0
                        is_same_line = abs(curr['cy'] - prev['cy']) < avg_h * 0.6
                        if is_same_line:
                            x_gap = curr['rect']['x'] - (prev['rect']['x'] + prev['rect']['width'])
                            
                        # Расстояние между левыми краями (чтобы не склеивать разные колонки/меню)
                        x_align_diff = abs(curr['rect']['x'] - prev['rect']['x'])
                        
                        if gap > avg_h * 1.2 or \
                           (is_same_line and x_gap > avg_h * 2.5) or \
                           (not is_same_line and x_align_diff > avg_h * 4.0) or \
                           txt.startswith(('•', '-', '*', '1.', '2.', '3.')):
                            paragraphs.append(current_para)
                            current_para = [curr]
                        else:
                            current_para.append(curr)
                    paragraphs.append(current_para)
                    
                    group_blocks = []
                    
                    for p_idx, para in enumerate(paragraphs):
                        # Clean and filter lines
                        clean_lines = []  # (clean_text, original_ocr_line_data)
                        for l in para:
                            txt = self.clean_text(l['text']).strip()
                            if len(txt) == 1 and not txt.isalnum() and txt not in "!?.,":
                                continue
                            if txt:
                                clean_lines.append((txt, l))
                        
                        if not clean_lines:
                            continue
                        
                        raw_text = " ".join([cl[0] for cl in clean_lines])
                                    
                        raw_text = ' '.join(raw_text.split())
                        
                        if len(raw_text) < 2 or self.is_garbage(raw_text):
                            continue
                        
                        # Use the robust area background color to avoid hitting text or borders
                        para_bg = area_bg_color
                        
                        # ── Smart Name Detection ──
                        p_name = None
                        text_to_translate = raw_text
                        translate_combined = False
                        
                        if ":" in raw_text:
                            parts = raw_text.split(":", 1)
                            candidate = parts[0].strip()
                            rest = parts[1].strip()
                            if 0 < len(candidate) < 25 and len(candidate.split()) <= 3 and not any(c.isdigit() for c in candidate):
                                p_name = candidate
                                text_to_translate = rest
                        elif len(clean_lines) > 1:
                            # Собираем все куски текста, которые находятся на той же визуальной строке (Y-координате)
                            first_line_cy = clean_lines[0][1]['cy']
                            first_line_height = clean_lines[0][1]['rect']['height']
                            
                            first_line_parts = []
                            rest_parts = []
                            for text_str, box in clean_lines:
                                if abs(box['cy'] - first_line_cy) < first_line_height * 0.6:
                                    first_line_parts.append(text_str)
                                else:
                                    rest_parts.append(text_str)
                                    
                            first_line_full = " ".join(first_line_parts).strip()
                            if first_line_full and first_line_full[-1] not in ".!?,;:-" and rest_parts:
                                words = first_line_full.split()
                                if 0 < len(words) <= 5: # Разрешаем до 5 слов для длинных имен
                                    # Проверяем, что большинство слов с большой буквы (Title Case)
                                    cap_count = sum(1 for w in words if w and w[0].isupper())
                                    if cap_count == len(words) or (len(words) > 1 and cap_count >= len(words) - 1):
                                        p_name = first_line_full
                                        # Use smartly joined raw_text to preserve kerning for the rest of the text
                                        text_to_translate = raw_text[len(first_line_full):].strip()
                        elif len(raw_text.split()) <= 5 and len(raw_text) <= 35 and raw_text[0].isupper() and not any(c in raw_text for c in ".,!?;=~<>%"):
                            p_name = raw_text
                            text_to_translate = ""
                            
                        # ── Translate ──
                        if p_name or text_to_translate:
                            loop = asyncio.get_event_loop()
                            import functools
                            
                            tasks = []
                            if p_name:
                                t_name = functools.partial(self.translator.translate, p_name, engine, target_lang, from_lang=src_lang)
                                tasks.append(loop.run_in_executor(None, t_name))
                                
                            if text_to_translate:
                                t_text = functools.partial(self.translator.translate, text_to_translate, engine, target_lang, from_lang=src_lang)
                                tasks.append(loop.run_in_executor(None, t_text))
                                
                            results = await asyncio.gather(*tasks)
                            
                            engine_used = "—"
                            if p_name:
                                res_name, e1 = results.pop(0)
                                p_name = res_name.strip() if res_name else None
                                engine_used = e1
                                
                            if text_to_translate:
                                translated, e2 = results.pop(0)
                                engine_used = e2
                            else:
                                translated = ""
                            
                            # Smart punctuation restoration: if original ends with a dot but translation doesn't
                            if translated and text_to_translate:
                                orig_end = text_to_translate.strip()[-1]
                                trans_end = translated.strip()[-1]
                                if trans_end not in ".!?":
                                    if orig_end in ".!?":
                                        if trans_end in ",;:":
                                            translated = translated.strip()[:-1] + orig_end
                                        else:
                                            translated += orig_end
                                    elif len(translated) > 15 and translated[0].isupper():
                                        if trans_end in ",;:":
                                            translated = translated.strip()[:-1] + "."
                                        else:
                                            translated += "."
                        else:
                            translated = ""
                            engine_used = "—"
                        
                        text_color = QColor(255, 255, 255)
                        
                        # ── Single Paragraph Block for overlay ──
                        # Emit one block for the entire paragraph, let Qt word-wrap it naturally.
                        # We format sentences onto new lines for a cleaner JRPG feel.
                        if translated:
                            # Insert newlines after sentence-ending punctuation
                            import re
                            text = re.sub(r'([.?!])\s+', r'\1\n', translated)
                            
                            l_xmin = min([w[1]['rect']['x'] for w in clean_lines])
                            l_ymin = min([w[1]['rect']['y'] for w in clean_lines])
                            l_xmax = max([w[1]['rect']['x'] + w[1]['rect']['width'] for w in clean_lines])
                            l_ymax = max([w[1]['rect']['y'] + w[1]['rect']['height'] for w in clean_lines])
                            avg_h = sum([w[1]['rect']['height'] for w in clean_lines]) / len(clean_lines)
                            
                            group_blocks.append({
                                'text': text,
                                'name': p_name,
                                'line_height': avg_h,
                                'is_bold': False,
                                'text_color': text_color,
                                'outline_color': QColor(0, 0, 0),
                                'has_outline': True,
                                'engine': engine_used,
                                'bg_color': para_bg,
                                'rect': QRect(int(area.x() + l_xmin), int(area.y() + l_ymin),
                                              int(l_xmax - l_xmin), int(l_ymax - l_ymin))
                            })
                        else:
                            # Name-only fallback
                            if clean_lines:
                                l_xmin = min([w[1]['rect']['x'] for w in clean_lines])
                                l_ymin = min([w[1]['rect']['y'] for w in clean_lines])
                                l_xmax = max([w[1]['rect']['x'] + w[1]['rect']['width'] for w in clean_lines])
                                l_ymax = max([w[1]['rect']['y'] + w[1]['rect']['height'] for w in clean_lines])
                                
                                group_blocks.append({
                                    'text': "",
                                    'name': p_name,
                                    'is_bold': False,
                                    'text_color': text_color,
                                    'outline_color': QColor(0, 0, 0),
                                    'has_outline': True,
                                    'engine': engine_used,
                                    'bg_color': para_bg,
                                    'rect': QRect(int(area.x() + l_xmin), int(area.y() + l_ymin),
                                                  int(l_xmax - l_xmin), int(l_ymax - l_ymin))
                                })

                        
                    if not group_blocks:
                        continue
                        
                    x_min = min([l['rect']['x'] for l in group])
                    y_min = min([l['rect']['y'] for l in group])
                    x_max = max([l['rect']['x'] + l['rect']['width'] for l in group])
                    y_max = max([l['rect']['y'] + l['rect']['height'] for l in group])
                    gx, gy = int(x_min), int(y_min)
                    gw = int(area.width() - gx - 5)
                    gh = int(y_max - y_min)
                    
                    if gw < 50:
                        gw = int(x_max - x_min)
                    
                    abs_rect = QRect(int(area.x() + gx), int(area.y() + gy), gw, gh)
                    
                    all_translations.append({
                        'rect': abs_rect,
                        'area_rect': QRect(area),
                        'blocks': group_blocks,
                        'bg_color': area_bg_color,
                        'font_pixel_size': 13, 
                        'area_index': idx + 1,
                        'group_index': g_idx
                    })

            self.new_translation.emit(all_translations)
            
            if self.settings.get('manual_once'):
                break

            try:
                await asyncio.wait_for(self.manual_trigger.wait(), timeout=self.settings.get('interval', 1.0))
            except asyncio.TimeoutError:
                pass
            
            self.manual_trigger.clear()
            
            # GC to prevent memory leaks from PyTorch/OpenCV over long sessions
            import gc
            gc.collect()
