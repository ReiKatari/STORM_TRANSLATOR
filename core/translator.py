import concurrent.futures
import translators as ts
from deep_translator import GoogleTranslator, MyMemoryTranslator
from collections import Counter
import time

class TranslationManager:
    def __init__(self):
        self.engines = {
            "Google": self._translate_google,
            "DeepL": self._translate_deepl,
            "Yandex": self._translate_yandex,
            "Papago": self._translate_papago,
            "Bing": self._translate_bing,
            "Baidu": self._translate_baidu,
            "DeepSeek": self._translate_deepseek,
            "ArgosOffline": self._translate_argos
        }

    def translate(self, text, engine_name="Google", target_lang="ru", from_lang="auto"):
        if not text.strip():
            return "", ""
        
        if engine_name == "AGGREGATION":
            return self.aggregate_translate(text, target_lang, from_lang)
            
        handler = self.engines.get(engine_name)
        if not handler:
            return f"[Error: Unknown engine {engine_name}]", "None"
            
        try:
            res = handler(text, target_lang, from_lang)
            if res and not str(res).startswith("[Error"):
                return res, engine_name
        except Exception:
            pass # Continue to fallback
            
        # Seamless Fallback to Google if primary fails
        if engine_name != "Google":
            try:
                res_fb = self._translate_google(text, target_lang, from_lang)
                if res_fb and not str(res_fb).startswith("[Error"):
                    return res_fb, f"Google (Fallback from {engine_name})"
            except Exception:
                pass
                
        return "[Error: All Translation Engines Failed]", engine_name

    def aggregate_translate(self, text, target_lang="ru", from_lang="auto"):
        """Runs multiple engines in parallel and picks the best or most common result."""
        selected_engines = ["Google", "Bing", "Papago", "DeepL"]
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            print(f"DEBUG AGGREGATOR RCVD TEXT: '{text}'")
            future_to_engine = {executor.submit(self.engines[name], text, target_lang, from_lang): name for name in selected_engines}
            for future in concurrent.futures.as_completed(future_to_engine):
                engine_name = future_to_engine[future]
                try:
                    res = future.result()
                    if res and not str(res).startswith("[Error"):
                        results.append((res, engine_name))
                except Exception as e:
                    print(f"Aggregation engine {engine_name} failed: {e}")
                    continue
        
        if not results:
            res = self._translate_google(text, target_lang, from_lang)
            return res, "Google (Fallback)"
            
        valid_results = [r for r in results if r[0].strip().lower() != text.strip().lower()]
        if valid_results:
            for pref in ["DeepL", "Bing", "Google", "Papago"]:
                for r in valid_results:
                    if r[1] == pref:
                        return r[0], f"AGGR ({r[1]})"
            return valid_results[0][0], f"AGGR ({valid_results[0][1]})"

        return results[0][0], f"AGGR ({results[0][1]})"

    def _translate_google(self, text, lang, from_lang="auto"):
        try:
            return GoogleTranslator(source=from_lang, target=lang).translate(text)
        except Exception as e:
            return f"[Error Google]: {str(e)}"

    def _translate_deepl(self, text, lang, from_lang="auto"):
        try:
            return ts.translate_text(text, translator='deepl', from_language=from_lang, to_language=lang)
        except Exception as e:
            return f"[Error DeepL]: Connection blocked or broken lib. {str(e)}"

    def _translate_yandex(self, text, lang, from_lang="auto"):
        # Direct HTTP request for Yandex to bypass broken ts package
        import requests, uuid
        url = "https://translate.yandex.net/api/v1/tr.json/translate"
        params = {
            "id": uuid.uuid4().hex + "-0-0",
            "srv": "android"
        }
        if from_lang == 'auto':
            params["lang"] = lang
        else:
            params["lang"] = f"{from_lang}-{lang}"
        
        try:
            resp = requests.post(url, params=params, data={"text": text, "options": 4}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if "text" in data and len(data["text"]) > 0:
                    return data["text"][0]
            return f"[Error Yandex]: HTTP {resp.status_code} - {resp.text}"
        except Exception as e:
            return f"[Error Yandex]: {str(e)}"

    def _translate_papago(self, text, lang, from_lang="auto"):
        try:
            return ts.translate_text(text, translator='papago', from_language=from_lang, to_language=lang)
        except Exception as e:
            return f"[Error Papago]: {str(e)}"

    def _translate_bing(self, text, lang, from_lang="auto"):
        try:
            return ts.translate_text(text, translator='bing', from_language=from_lang, to_language=lang)
        except Exception as e:
            return f"[Error Bing]: {str(e)}"

    def _translate_baidu(self, text, lang, from_lang="auto"):
        try:
            return ts.translate_text(text, translator='baidu', from_language=from_lang, to_language=lang)
        except Exception as e:
            return f"[Error Baidu]: {str(e)}"

    def _translate_deepseek(self, text, lang, from_lang="auto"):
        import requests, os
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            try:
                with open("deepseek_key.txt", "r") as f:
                    api_key = f.read().strip()
            except:
                return "[Error DeepSeek]: Создайте файл deepseek_key.txt в папке программы и впишите туда ваш API ключ"

        url = "https://api.deepseek.com/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        lang_name = "Russian" if lang == "ru" else lang
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": f"You are a highly skilled professional game translator. Translate the following video game dialogue into {lang_name}. Return ONLY the final translated text. Maintain context, keep it natural and avoid literal translations."},
                {"role": "user", "content": text}
            ],
            "temperature": 0.3
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            return f"[Error DeepSeek API]: HTTP {resp.status_code} - {resp.text}"
        except Exception as e:
            return f"[Error DeepSeek]: {str(e)}"

    def _translate_argos(self, text, lang, from_lang="auto"):
        try:
            import argostranslate.package
            import argostranslate.translate
            
            if from_lang == 'auto': from_lang = 'en'
            if lang == 'auto': lang = 'ru'
            
            translatedText = argostranslate.translate.translate(text, from_lang, lang)
            return translatedText
        except ImportError:
            return "[Error Argos]: Установите пакет (pip install argostranslate) и скачайте модели через код"
        except Exception as e:
            return f"[Error Argos]: {str(e)}"
