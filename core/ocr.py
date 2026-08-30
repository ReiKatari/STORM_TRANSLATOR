import asyncio
try:
    import winsdk.windows.media.ocr as ocr
    import winsdk.windows.graphics.imaging as imaging
    import winsdk.windows.storage.streams as streams
except ImportError:
    ocr = None
    imaging = None
    streams = None
from PIL import Image
import numpy as np
import io
import cv2

class OCRManager:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self.engines = {} 
        self._easy_reader = None
        self._paddle_engine = None
        self._warmed_up = False
        self._gpu_available = None  # None = not checked, True/False = checked
        self._initialized = True
        
    def check_gpu_status(self):
        """Check if CUDA or MPS is available for acceleration."""
        if self._gpu_available is not None:
            return self._gpu_available
        try:
            import torch
            if torch.cuda.is_available():
                self._gpu_available = "CUDA"
                return "CUDA"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                self._gpu_available = "MPS"
                return "MPS"
        except (ImportError, OSError) as e:
            print(f"DEBUG: GPU Check failed (torch not available or corrupt): {e}")
        except Exception as e:
            print(f"DEBUG: Unexpected error checking GPU: {e}")
        self._gpu_available = False
        return False
        
    def warmup(self, lang_code="en-US"):
        """Pre-initialize heavy engines in background. Call on app start."""
        if self._warmed_up:
            return
        print("DEBUG: Warming up OCR engines...")
        import threading
        def _warmup_thread():
            try:
                # 1. EasyOCR (heaviest)
                self.get_easy_reader(lang_code)
                print("DEBUG: EasyOCR warmed up.")
            except Exception as e:
                print(f"DEBUG: EasyOCR warmup failed: {e}")

            self._warmed_up = True
            print("DEBUG: All engines warmed up!")
        t = threading.Thread(target=_warmup_thread, daemon=True)
        t.start()

    def get_win_engine(self, lang_code="en-US"):
        if lang_code not in self.engines:
            if ocr is None:
                print("DEBUG: Windows OCR (winsdk) not installed.")
                self.engines[lang_code] = None
                return None
            try:
                import winsdk.windows.globalization as glob
                lang = glob.Language(lang_code)
                self.engines[lang_code] = ocr.OcrEngine.try_create_from_language(lang)
            except:
                self.engines[lang_code] = ocr.OcrEngine.try_create_from_user_profile_languages()
        return self.engines[lang_code]

    def get_easy_reader(self, lang_code="en-US"):
        target_langs = ['en']
        if 'ru' in lang_code.lower():
            target_langs = ['ru', 'en']
        elif 'ja' in lang_code.lower():
            target_langs = ['ja', 'en']
            
        # Check if we have a cached reader with same languages
        if self._easy_reader and hasattr(self, '_easy_langs'):
            # Check if languages match
            if set(self._easy_langs) == set(target_langs):
                return self._easy_reader
        
        # Initialize new reader
        import easyocr
        print(f"DEBUG: Initializing EasyOCR with languages: {target_langs}")
        self._easy_reader = easyocr.Reader(target_langs)
        self._easy_langs = target_langs # Track manually
        return self._easy_reader

    async def recognize(self, pil_image, lang_code="en-US", engine="Windows", use_preprocess=True):
        """Main OCR entry point with engine switching."""
        print(f"DEBUG: OCR REQUESTED WITH ENGINE: {engine}")
        if engine == "Paddle":
            return await self.recognize_paddle(pil_image, use_preprocess=use_preprocess)
        elif engine == "EasyOCR":
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, self.recognize_easy, pil_image, lang_code)
            if "en" in lang_code.lower():
                res = self.apply_autocorrect(res)
            return res
        elif engine == "MultiOCR":
            return await self.recognize_multi(pil_image, lang_code)
        elif engine == "FastOCR":
            # FastOCR = WindowsOCR with minimal preprocessing (speed mode)
            return await self.recognize_win(pil_image, lang_code, use_preprocess=True)
        elif engine == "Tesseract":
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, self.recognize_tesseract, pil_image, lang_code)
            if "en" in lang_code.lower():
                res = self.apply_autocorrect(res)
            return res
        return await self.recognize_win(pil_image, lang_code, use_preprocess=use_preprocess)



    async def recognize_paddle(self, pil_image, use_preprocess=True):
        """High-accuracy recognition using PaddleOCR v2 (Speed Settings)."""
        try:
            if use_preprocess:
                # Use Neural Preprocess (Smooth 2x)
                pil_image = self.preprocess_neural(pil_image, scale=2)
                
            from paddleocr import PaddleOCR
            import logging
            logging.getLogger('ppocr').setLevel(logging.ERROR)
            import os
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
            
            if not hasattr(self, 'paddle_engine'):
                print("Initializing PaddleOCR (Speed Settings + No MKLDNN)...")
                # Removed experimental params to prevent crashes
                self.paddle_engine = PaddleOCR(
                    use_angle_cls=False,
                    lang='en',
                    det_db_thresh=0.3,
                    det_db_box_thresh=0.4,
                    enable_mkldnn=False # FIX: Setup crash on Windows
                )

            img_np = np.array(pil_image)
            
            # PaddleOCR requires 3-channel image
            if len(img_np.shape) == 2:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
                
            # Run inference (No arguments to avoid version conflicts)
            result = self.paddle_engine.ocr(img_np)
            
            formatted = []
            if result and result[0]:
                 # print(f"DEBUG: Paddle Result: {result}")
                 scale = 3 if use_preprocess else 1
                 padding = 0
                 
                 for line in result[0]:
                    try:
                        box, (text, conf) = line
                    except Exception: continue
                    
                    if conf < 0.4: continue # Lower confidence floor for pixel fonts
                        
                    x_min = min([p[0] for p in box])
                    y_min = min([p[1] for p in box])
                    x_max = max([p[0] for p in box])
                    y_max = max([p[1] for p in box])
                    
                    formatted.append({
                        'text': text,
                        'rect': {'x': (x_min/scale)-padding, 'y': (y_min/scale)-padding, 
                                 'width': (x_max-x_min)/scale, 'height': (y_max-y_min)/scale}
                    })
            
            # Use Y-bucket sorting (worker.py does main sort, but good to have here)
            formatted.sort(key=lambda r: (int(r['rect']['y'] / 15), r['rect']['x']))
            return formatted
            
        except Exception as e:
            error_msg = str(e)
            if "ConvertPirAttribute2RuntimeAttribute" in error_msg:
                print("PaddleOCR Error: oneDNN compatibility issue in PaddlePaddle 3.3.0")
                print("FIX: Run 'pip install paddlepaddle==3.2.2' to downgrade to a working version")
            else:
                print(f"PaddleOCR Error: {e}")
            return []

    async def recognize_win(self, pil_image, lang_code="en-US", use_preprocess=True):
        """Recognition using Windows 10/11 system OCR."""
        win_engine = self.get_win_engine(lang_code)
        if not win_engine:
            return []
            
        scale = 1
        if use_preprocess:
            scale = 5  # v0.2.1: Higher scale for pixel fonts
            pil_image = self.preprocess(pil_image, scale=scale)
            
        byte_io = io.BytesIO()
        pil_image.save(byte_io, format='PNG')
        stream = streams.InMemoryRandomAccessStream()
        writer = streams.DataWriter(stream)
        writer.write_bytes(byte_io.getvalue())
        await writer.store_async()
        await writer.flush_async()
        
        decoder = await imaging.BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        
        result = await win_engine.recognize_async(bitmap)
        
        lines_data = []
        for line in result.lines:
            valid_words = []
            for word in line.words:
                w_text = word.text.strip()
                if w_text:
                    valid_words.append(word)
            
            if not valid_words:
                continue
                
            first_box = valid_words[0].bounding_rect
            x_min, y_min = first_box.x, first_box.y
            x_max = first_box.x + first_box.width
            y_max = first_box.y + first_box.height
            
            for i in range(1, len(valid_words)):
                box = valid_words[i].bounding_rect
                x_min = min(x_min, box.x)
                y_min = min(y_min, box.y)
                x_max = max(x_max, box.x + box.width)
                y_max = max(y_max, box.y + box.height)
            
            lines_data.append({
                'text': line.text,
                'rect': {
                    'x': x_min / scale,
                    'y': y_min / scale,
                    'width': (x_max - x_min) / scale,
                    'height': (y_max - y_min) / scale
                }
            })
        return lines_data

    def is_tesseract_installed(self):
        import os
        import sys
        tesseract_paths = []
        if hasattr(sys, '_MEIPASS'):
            tesseract_paths.append(os.path.join(sys._MEIPASS, "Tesseract-OCR", "tesseract.exe"))
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
        tesseract_paths.append(os.path.join(base_path, "Tesseract-OCR", "tesseract.exe"))
        tesseract_paths.extend([
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\Tesseract-OCR\tesseract.exe",
        ])
        for path in tesseract_paths:
            if os.path.exists(path):
                return True
        return False

    def recognize_tesseract(self, pil_image, lang_code="en-US"):
        """Recognition using Tesseract OCR (Classic, works well with pixel fonts)."""
        try:
            import pytesseract
            import os
            import sys
            
            # Auto-detect Tesseract path
            tesseract_paths = []
            
            # 1. PyInstaller bundled (inside EXE via _MEIPASS)
            if hasattr(sys, '_MEIPASS'):
                tesseract_paths.append(os.path.join(sys._MEIPASS, "Tesseract-OCR", "tesseract.exe"))
            
            # 2. Next to script/exe
            base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
            tesseract_paths.append(os.path.join(base_path, "Tesseract-OCR", "tesseract.exe"))
            
            # 3. Common installation paths
            tesseract_paths.extend([
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                r"C:\Tesseract-OCR\tesseract.exe",
            ])
            
            for path in tesseract_paths:
                if os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    print(f"DEBUG: Tesseract found at: {path}")
                    break

            
            # Preprocess for pixel fonts: Use Binarization to destroy background textures
            # and isolate pure text. This prevents Tesseract from hallucinating words in pixel art.
            scale = 5  
            img_processed = self.preprocess(pil_image, scale=scale)
            
            # Map lang codes
            tess_lang = 'eng'
            if 'ru' in lang_code.lower():
                tess_lang = 'rus'
            elif 'ja' in lang_code.lower():
                tess_lang = 'jpn'
            elif 'zh' in lang_code.lower():
                tess_lang = 'chi_sim'
            elif 'ko' in lang_code.lower():
                tess_lang = 'kor'
            elif 'de' in lang_code.lower():
                tess_lang = 'deu'
            elif 'fr' in lang_code.lower():
                tess_lang = 'fra'
            
            # Pixel Art Tesseract Config
            # --psm 12 -> Sparse text with OSD. Find as much text as possible in no particular order. Ideal for separate bubbles.
            custom_config = r'--oem 3 --psm 12'
            
            # Get detailed data with bounding boxes
            data = pytesseract.image_to_data(img_processed, lang=tess_lang, config=custom_config, output_type=pytesseract.Output.DICT)
            
            # Group words into lines, but strictly separate distant words
            lines = {}
            virtual_line_counter = 0
            
            for i, text in enumerate(data['text']):
                if not text.strip():
                    continue
                conf = int(data['conf'][i])
                print(f"DEBUG: Tesseract word: '{text}' conf={conf}")  # Debug
                if conf < 5:  # Very low threshold for pixel fonts
                    continue
                    
                orig_line_num = data['line_num'][i]
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                
                # Find an existing line to append to, or create a new one if the X-gap is too large
                assigned_line = None
                for v_id, l_data in lines.items():
                    if l_data['orig_line'] == orig_line_num:
                        gap = x - l_data['x_max']
                        # If the horizontal gap is less than 2.5 times the height, it's the same visual line
                        if gap < h * 2.5:
                            assigned_line = v_id
                            break
                            
                if assigned_line is None:
                    virtual_line_counter += 1
                    assigned_line = virtual_line_counter
                    lines[assigned_line] = {'orig_line': orig_line_num, 'words': [], 'x_min': float('inf'), 'y_min': float('inf'), 'x_max': 0, 'y_max': 0}
                
                lines[assigned_line]['words'].append(text)
                lines[assigned_line]['x_min'] = min(lines[assigned_line]['x_min'], x)
                lines[assigned_line]['y_min'] = min(lines[assigned_line]['y_min'], y)
                lines[assigned_line]['x_max'] = max(lines[assigned_line]['x_max'], x + w)
                lines[assigned_line]['y_max'] = max(lines[assigned_line]['y_max'], y + h)
            
            # Convert to result format
            results = []
            padding = 0
            for line_num, line_data in sorted(lines.items()):
                text = ' '.join(line_data['words'])
                results.append({
                    'text': text,
                    'rect': {
                        'x': (line_data['x_min'] / scale) - padding,
                        'y': (line_data['y_min'] / scale) - padding,
                        'width': (line_data['x_max'] - line_data['x_min']) / scale,
                        'height': (line_data['y_max'] - line_data['y_min']) / scale
                    }
                })
            
            print(f"DEBUG: Tesseract found {len(results)} lines")
            return results
            
        except ImportError:
            print("ERROR: pytesseract not installed. Run: pip install pytesseract")
            print("       Also install Tesseract-OCR: https://github.com/UB-Mannheim/tesseract/wiki")
            return []
        except Exception as e:
            print(f"Tesseract Error: {e}")
            return []

    def recognize_easy(self, pil_image, lang_code="en-US"):
        """Recognition using EasyOCR (Deep Learning)."""
        reader = self.get_easy_reader(lang_code)
        
        img_np = np.array(pil_image)
        # Let EasyOCR handle upscaling using its built-in optimized magnification
        # Use width_ths=0.8 to aggressively merge letters within words that have wide kerning
        results = reader.readtext(img_np, mag_ratio=2.5, width_ths=0.8, paragraph=False)
        
        final_results = []
        for bbox, text, prob in results:
             if prob < 0.25:
                 continue
             x_min = min([p[0] for p in bbox])
             y_min = min([p[1] for p in bbox])
             x_max = max([p[0] for p in bbox])
             y_max = max([p[1] for p in bbox])
             
             # EasyOCR returns coordinates relative to the original image space
             final_results.append({
                'text': text,
                'confidence': prob,
                'rect': {
                    'x': x_min,
                    'y': y_min,
                    'width': (x_max - x_min),
                    'height': (y_max - y_min)
                }
             })
             
        # Sort: Top to Bottom, Left to Right
        final_results.sort(key=lambda r: (int(r['rect']['y'] / 10), r['rect']['x']))
        
        return final_results


    def preprocess(self, pil_image, scale=5, for_windows_ocr=False):
        """
        Prepare image for OCR.
        
        v0.2.1 Strategy (Pixel Font Optimized):
        - ALL engines: Grayscale -> Binarization (Otsu) -> Inversion
        - Scale 5x for better character detection
        - Pure black text on white background
        
        Args:
            pil_image: Input PIL Image
            scale: Upscale factor (default 5x for pixel fonts)
            for_windows_ocr: Ignored in v0.2.1 - all engines use same preprocessing
        """
        img_np = np.array(pil_image)
        
        # 1. Add padding (helps edge detection)
        padding = 15
        if len(img_np.shape) == 3:
            img_padded = cv2.copyMakeBorder(img_np, padding, padding, padding, padding, 
                                            cv2.BORDER_CONSTANT, value=[0, 0, 0])
        else:
            img_padded = cv2.copyMakeBorder(img_np, padding, padding, padding, padding, 
                                            cv2.BORDER_CONSTANT, value=0)
        
        # 2. Upscale with INTER_NEAREST to preserve pixel edges (critical for pixel fonts!)
        # LANCZOS blurs pixel fonts, NEAREST keeps them sharp
        h, w = img_padded.shape[:2]
        img_scaled = cv2.resize(img_padded, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
        
        # 3. Convert to grayscale
        if len(img_scaled.shape) == 3:
            img_gray = cv2.cvtColor(img_scaled, cv2.COLOR_RGB2GRAY)
        else:
            img_gray = img_scaled
        
        # 4. Otsu Binarization (pure black/white - critical for pixel fonts)
        # This creates maximum contrast and removes any anti-aliasing artifacts
        _, img_binary = cv2.threshold(img_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 5. Smart Inversion (OCR prefers black text on white background)
        # Check border pixels to determine background color
        h, w = img_binary.shape
        border_mean = (img_binary[0, :].mean() + img_binary[h-1, :].mean() + 
                       img_binary[:, 0].mean() + img_binary[:, w-1].mean()) / 4
        
        if border_mean < 127:
            # Dark border = dark background = invert to get black text on white
            img_binary = cv2.bitwise_not(img_binary)
        
        result = Image.fromarray(img_binary)
        return result
        
        return result

    def preprocess_neural(self, pil_image, scale=4):
        """
        Preprocessing specifically for Neural Nets (EasyOCR/Paddle).
        - Smooth scaling (LANCZOS/CUBIC) to look like 'photo' text
        - Grayscale ONLY (No binarization) to preserve details
        """
        img_np = np.array(pil_image)
        
        # 1. Padding
        padding = 10
        if len(img_np.shape) == 3:
            img_padded = cv2.copyMakeBorder(img_np, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=[0, 0, 0])
        else:
            img_padded = cv2.copyMakeBorder(img_np, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=0)
        # 2. Smooth Scaling (Neural nets hate pixel jagging, but for pixel fonts Nearest is often better)
        h, w = img_padded.shape[:2]
        img_scaled = cv2.resize(img_padded, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
        
        # 3. Grayscale
        if len(img_scaled.shape) == 3:
            img_gray = cv2.cvtColor(img_scaled, cv2.COLOR_RGB2GRAY)
        else:
            img_gray = img_scaled
            
        # 4. Invert if dark background (Neural nets prefer black text on white)
        h, w = img_gray.shape
        # Sample border to guess bg color
        border_mean = (img_gray[0, :].mean() + img_gray[h-1, :].mean() + img_gray[:, 0].mean() + img_gray[:, w-1].mean()) / 4
        if border_mean < 100:
            img_gray = cv2.bitwise_not(img_gray)
        
        return Image.fromarray(img_gray)

    def preprocess_morph(self, pil_image, scale=5, op='dilate', iterations=1):
        """
        Morphological operations to fix thin/broken or thick/touching text.
        op: 'dilate' (thicken), 'erode' (thin)
        """
        # 1. Standard Preprocess first (Binarization + Inversion)
        pil_binary = self.preprocess(pil_image, scale=scale)
        img_np = np.array(pil_binary)
        
        # 2. Kernel setup
        kernel = np.ones((2, 2), np.uint8) # Small 2x2 kernel
        
        # 3. Apply morphology
        # Note: Since image is inverted (white text on black via preprocess step?), 
        # wait, preprocess returns BLACK TEXT on WHITE background (bitwise_not).
        # So DILATE would expand BLACK regions (making text THICKER).
        # ERODE would shrink BLACK regions (making text THINNER).
        # OpenCV standard: Dilate = expand WHITE. Erode = shrink WHITE.
        # But our image is Black-on-White (0 on 255).
        # So Dilate (expand 255) -> eats into 0 (text gets thinner).
        # Erode (shrink 255) -> expands 0 (text gets thicker).
        
        # Invert first to make text White-on-Black standard for morphology
        img_inv = cv2.bitwise_not(img_np)
        
        if op == 'dilate':
            # Expand white text
            processed = cv2.dilate(img_inv, kernel, iterations=iterations)
        else:
            # Shrink white text
            processed = cv2.erode(img_inv, kernel, iterations=iterations)
            
        # Invert back to Black-on-White
        final = cv2.bitwise_not(processed)
        
        return Image.fromarray(final)

    def preprocess_raw(self, pil_image, scale=3):
        """Minimal preprocessing: just scale up with INTER_NEAREST, no binarization."""
        img_np = np.array(pil_image)
        h, w = img_np.shape[:2]
        img_scaled = cv2.resize(img_np, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
        return Image.fromarray(img_scaled)

    def score_result(self, text, lang_code="en-US"):
        """
        Score OCR result using heuristics.
        Higher score = better result.
        """
        if not text or len(text.strip()) < 2:
            return 0
        
        text = text.strip()
        total_chars = len(text)
        
        # 1. Valid Character Ratio
        # If English, strict ASCII check. If Russian, Cyrillic check.
        is_english = "en" in lang_code.lower()
        is_russian = "ru" in lang_code.lower()
        
        valid_chars = 0
        garbage_chars = 0
        
        for c in text:
            if c.isspace() or c in ".,!?'-:\"$%()":
                valid_chars += 1
                continue
                
            code = ord(c)
            is_latin = 65 <= code <= 90 or 97 <= code <= 122
            is_cyrillic = 1040 <= code <= 1103 or code == 1025 or code == 1105
            
            if is_english:
                if is_latin: valid_chars += 1
                elif is_cyrillic: garbage_chars += 1  # Penalty for Cyrillic in English text
                else: garbage_chars += 0.5 # Unknown symbols
            elif is_russian:
                if is_cyrillic: valid_chars += 1
                elif is_latin: garbage_chars += 0.5 # Latin in Russian is okay sometimes (names)
                else: garbage_chars += 0.5
            else:
                # Fallback for other languages - generic isalpha
                if c.isalpha(): valid_chars += 1
                else: garbage_chars += 0.5

        valid_ratio = valid_chars / total_chars if total_chars > 0 else 0
        garbage_penalty = garbage_chars / total_chars if total_chars > 0 else 0
        
        # 2. Text length (more = better, but diminishing returns)
        length_score = min(100, len(text)) / 100
        
        # 3. Word count (more words = more complete)
        words = text.split()
        word_score = min(20, len(words)) / 20
        
        # 4. Penalty for repeated characters (like "ЕЕЕЕЕЕ")
        repeat_penalty = 0
        for i in range(1, len(text)):
            if text[i] == text[i-1]:
                repeat_penalty += 0.05 
        
        # 5. Dictionary Boost (Common Words)
        try:
            from resources.dict_en import COMMON_WORDS
        except ImportError:
            COMMON_WORDS = {"THE", "AND", "YOU", "FORCE", "CONTROLS"}

        found_common = 0
        for w in words:
            w_upper = w.upper().strip(".,!?\"'")
            if w_upper in COMMON_WORDS:
                found_common += 1
        
        dict_boost = min(40, found_common * 10) / 100 # Up to 0.4 boost
        
        # 6. Consonant Cluster Penalty (e.g. "MFNNACF")
        # Text with no vowels in long words is suspicious (unless abbreviations)
        vowels = "AEIOUaeiou"
        consonant_penalty = 0
        for w in words:
            if len(w) > 4 and not any(c in vowels for c in w):
                consonant_penalty += 0.2
        
        # Final score
        # Valid ratio is king. Dictionary boost helps resolve ties.
        score = (valid_ratio * 50) + (length_score * 20) + (word_score * 10) + (dict_boost * 30) - (garbage_penalty * 50) - (repeat_penalty * 20) - (consonant_penalty * 20)
        
        return max(0, score)

    def apply_autocorrect(self, results):
        """Clean pixel garbage and autocorrect in-place."""
        # DISABLED: Global autocorrect and regexes destroy valid text.
        return results
        
        try:
            from resources.dict_en import COMMON_WORDS
        except ImportError:
            COMMON_WORDS = {"THE", "AND", "YOU", "FORCE", "CONTROLS"}

        import difflib
        
        # Pixel font common character confusions (OCR mistakes)
        # These are applied BEFORE word-level fixes
        subs = {
            '0': 'O', '1': 'I', '5': 'S', '8': 'B', 
            '6': 'G',  # Can be G or 6-looks-like-G in pixel fonts
            '3': 'E',  # 3 often confused with E
            '@': 'A', '$': 'S', '(': 'C',
            '|': 'I', 'l': 'I',  # Vertical lines
            '§': 'S', '&': 'A',  # Symbol confusions
        }
        
        # Special multi-char patterns for pixel fonts (applied to whole text)
        # These fix common OCR mistakes for THIS SPECIFIC GAME
        pixel_patterns = {
            # Character-level patterns
            '63': 'IS',  # Common: "IS" reads as "63"
            'UU': 'OUS',  # Common ending
            'LOrD': 'LORD',  # Case fix
            
            # Game-specific word patterns (MUST be unique/garbage, not real words!)
            'CONTAMINDUU': 'CONTAMINOUS',
            'CONTAMINDU': 'CONTAMINOUS', 
            'CONTINUE O': 'CONTAMINOUS.',  # Common misread
            'WORD': 'LORD',  # L often missed
            'FORD': 'LORD',  # F/L confusion
        }
        
        # Manual overrides for VERY broken words (ONLY GARBAGE, NOT REAL WORDS!)
        manual_fixes = {
            # Garbage -> POLLUTING
            "PHLLUTT": "POLLUTING", "PHLLUTING": "POLLUTING", "PDLLUT": "POLLUTING", "PDLLUTT": "POLLUTING",
            "PDLLNTT": "POLLUTING", "PDLLNT": "POLLUTING", "PLLUTING": "POLLUTING", "PLLUT": "POLLUTING",
            # Garbage -> CONTROLS
            "CONTRDLS": "CONTROLS", "CONTRDLE": "CONTROLS",
            # Garbage -> ARISES
            "ARKRFS": "ARISES", "ARKRES": "ARISES", "AR EFS": "ARISES",
            # Garbage -> MENACE
            "MFNNACF": "MENACE", "MFNACF": "MENACE",
            # Garbage -> THESE
            "THESF": "THESE",
            # Garbage -> ALL
            "AKK": "ALL", "AII": "ALL",
            # Multi-word garbage
            "ALL O7": "ALL OF"
            # NOTE: Do NOT add real words like ENHANCE, SOLUTION, CONTROL, FORCE, TALK, RAISE
            # They will corrupt normal text!
        }

        for item in results:
            w = item['text'].strip()
            w_upper = w.upper()
            w_original_case = w # Keep original for casing if needed, but we mostly just overwrite
            
            # -1. Apply pixel patterns (multi-char fixes like "63" -> "IS")
            for pattern, replacement in pixel_patterns.items():
                if pattern in w:
                    w = w.replace(pattern, replacement)
                if pattern in w_upper:
                    w_upper = w_upper.replace(pattern, replacement)
                    w = w_upper  # Use the fixed version
            
            # 0. Manual Override (Substring Replacement)
            # This handles cases where EasyOCR groups words like "THE ENHANCE"
            for bad, good in manual_fixes.items():
                if bad in w_upper:
                    # Replace keeping case if possible? No, just replace with UPPER/Title from dict
                    # Since we are aggressive, let's just replace the substring in the upper version
                    # and then set the text. OR, use regex/string replace on the original text case-insensitively.
                    # Simple approach: Replace in w_upper, then if changed, update item['text']
                    # logic: if bad word is found, replace it with good word.
                    
                    # Case insensitive replace
                    import re
                    pattern = re.compile(re.escape(bad), re.IGNORECASE)
                    w = pattern.sub(good, w)
                    
            item['text'] = w
            
            # 1. Pre-clean garbage chars if word not in dict
            w_upper = w.upper().strip(".,!?\"'-:;")
            if w_upper not in COMMON_WORDS:
                # Try simple substitutions
                w_clean = "".join([subs.get(c, c) for c in w])
                w_clean_upper = w_clean.upper().strip(".,!?\"'-:;")
                if w_clean_upper in COMMON_WORDS:
                    item['text'] = w_clean # Success
                    continue
            
            # 2. Autocorrect Logic - DISABLED
            # Aggressive difflib matching corrupted valid technical words and names (e.g. Engine -> Brow)
            # We let the raw OCR string pass to the Neural Translator (DeepL/Yandex) which will infer context correctly.
                     
        return results

    async def recognize_multi(self, pil_image, lang_code="en-US"):
        """
        Multi-engine OCR with Brute Force Voting & Early Exit.
        """
        print("DEBUG: MultiOCR v0.3.9 - Running CASCADING variants...")
        results = []
        
        # Helper to scale results back from preprocessed coordinates to original image coordinates
        def scale_results_back(res, scale, padding=10):
            """Divide OCR coordinates by scale factor and subtract padding to map back to original image space."""
            if not res:
                return res
            for r in res:
                rect = r['rect']
                rect['x'] = (rect['x'] / scale) - padding
                rect['y'] = (rect['y'] / scale) - padding
                rect['width'] = rect['width'] / scale
                rect['height'] = rect['height'] / scale
            return res
        
        # Helper to run and score
        async def run_variant(name, engine_func, img_arg, result_scale=1, result_padding=0):
            try:
                res = engine_func(img_arg)
                if asyncio.iscoroutine(res):
                    res = await res
                
                if res and isinstance(res, list) and len(res) > 0:
                    # Scale coordinates back if needed
                    if result_scale > 1:
                        res = scale_results_back(res, result_scale, result_padding)
                    
                    # Apply Autocorrect IN-PLACE for English
                    if "en" in lang_code.lower():
                        res = self.apply_autocorrect(res)
                        
                    text = " ".join([r['text'] for r in res])
                    score = self.score_result(text, lang_code)
                    print(f"DEBUG: {name}: '{text[:40]}...' score={score:.1f}")
                    return (name, res, text, score)
            except Exception as e:
                print(f"DEBUG: {name} failed: {e}")
            return None

        # 1. Prepare Images (5x scale + 15px padding added by preprocess)
        preprocess_scale = 5
        preprocess_padding = 15
        img_standard = self.preprocess(pil_image, scale=preprocess_scale)
        img_dilated = self.preprocess_morph(pil_image, scale=preprocess_scale, op='dilate')
        
        # 2. Phase 1: WindowsOCR (Fastest)
        # Variant A: Standard — recognize_win with use_preprocess=False returns coords in 5x space
        r1 = await run_variant('WinOCR_Standard', 
                               lambda i: self.recognize_win(i, lang_code, use_preprocess=False), 
                               img_standard, result_scale=preprocess_scale, result_padding=preprocess_padding)
        if r1: results.append(r1)
        
        # Variant B: Dilated
        r2 = await run_variant('WinOCR_Dilated', 
                               lambda i: self.recognize_win(i, lang_code, use_preprocess=False), 
                               img_dilated, result_scale=preprocess_scale, result_padding=preprocess_padding)
        if r2: results.append(r2)
        
        # EARLY EXIT CHECK
        if results:
            results.sort(key=lambda x: x[3], reverse=True)
            best_win = results[0]
            if best_win[3] >= 80: # Slightly higher threshold for confidence
                print(f"DEBUG: Early Exit (WinOCR Good Enough) - Score {best_win[3]:.1f}")
                return best_win[1]

        # 3. Phase 2: Heavy Artillery (Paddle + EasyOCR)
        print("DEBUG: WinOCR low score, engaging Heavy Artillery (Paddle + Easy)...")
        loop = asyncio.get_event_loop()
        
        # Define Wrappers
        def run_easy_manual(img_input):
            reader = self.get_easy_reader(lang_code)
            img_np = np.array(img_input)
            raw_res = reader.readtext(img_np)
            formatted = []
            scale = 3; padding = 10 
            for bbox, text, prob in raw_res:
                x_min = min([p[0] for p in bbox]); y_min = min([p[1] for p in bbox])
                x_max = max([p[0] for p in bbox]); y_max = max([p[1] for p in bbox])
                formatted.append({'text': text, 'rect': {'x': (x_min/scale)-padding, 'y': (y_min/scale)-padding, 'width': (x_max-x_min)/scale, 'height': (y_max-y_min)/scale}})
            formatted.sort(key=lambda r: (int(r['rect']['y'] / 15), r['rect']['x']))
            return formatted

        # Helper for generic execution
        async def run_managed_variant(name, img_arg, func):
             try:
                 # Check for Paddle lib presence before running
                 if "Paddle" in name:
                     try: import paddleocr
                     except ImportError: 
                         # print(f"DEBUG: skipping {name} (paddleocr not installed)")
                         return None
                 
                 res = await loop.run_in_executor(None, func, img_arg) if not asyncio.iscoroutinefunction(func) else await func(img_arg)
                 
                 # Unwrap if it's a coroutine result that returned a coroutine? No, basic await handles it.
                 # But notice: recognize_paddle IS async. 
                 
                 if res:
                     if "en" in lang_code.lower(): res = self.apply_autocorrect(res)
                     text = " ".join([r['text'] for r in res])
                     score = self.score_result(text, lang_code)
                     print(f"DEBUG: {name}: '{text[:40]}...' score={score:.1f}")
                     return (name, res, text, score)
             except Exception as e:
                 print(f"DEBUG: {name} failed: {e}")
             return None

        # PARALLEL RUN: EasyOCR (Std) + PaddleOCR (Max)
        # We run them together to save time (Python threads release GIL for IO/C++ libs)
        
        # Variant D: EasyOCR Std (Neural)
        img_easy_std = self.preprocess_neural(pil_image, scale=3)
        t_easy = run_managed_variant('EasyOCR_Standard', img_easy_std, run_easy_manual)
        
        # Variant E: PaddleOCR (Fast)
        async def run_paddle_wrapper(img):
            return await self.recognize_paddle(img, use_preprocess=True) # Helper handles preprocess
            
        t_paddle = run_managed_variant('PaddleOCR_Max', pil_image, run_paddle_wrapper) # Pass raw image, let it preprocess
        
        # Wait for both
        heavy_results = await asyncio.gather(t_easy, t_paddle)
        
        for r in heavy_results:
            if r: results.append(r)
        
        # Pick best result
        if not results:
            print("DEBUG: MultiOCR - No result!")
            return []
        
        results.sort(key=lambda x: x[3], reverse=True)
        best = results[0]
        print(f"DEBUG: MultiOCR WINNER: {best[0]} with score {best[3]:.1f}")
        
        return best[1]
