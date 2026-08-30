import json
import os
from PyQt6.QtCore import QRect

class SettingsManager:
    def __init__(self):
        self.settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings.json')
        self.defaults = {
            'geometry': [100, 100, 1100, 870],
            'engine': 'Google',
            'ocr_engine': 'EasyOCR',
            'interval': 1.0,
            'silent': False,
            'aggregate': False,
            'auto_update': True,
            'ui_lang': 'RU',
            'src_lang': 'English',
            'target_lang': 'Russian',
            'on_top': False,
            'opacity': 100,
            'theme': 'Dark (Default)',
            'retroarch_pause': False,
            'translation_areas': [],
            'areas_enabled': [],
            'exclusion_zones': [],
            'exclusion_zones_enabled': []
        }
        self.data = self.load()

    def load(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    return {**self.defaults, **json.load(f)}
            except Exception:
                return self.defaults.copy()
        return self.defaults.copy()

    def save(self):
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, key, default=None):
        if default is not None:
            return self.data.get(key, default)
        return self.data.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()
