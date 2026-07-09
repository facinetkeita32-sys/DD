import json
import os


class Translator:
    def __init__(self):
        self._translations = {}
        self._current_lang = 'en'
        self._load_translations()

    def _load_translations(self):
        dir_path = os.path.dirname(os.path.abspath(__file__))
        for fname in os.listdir(dir_path):
            if fname.endswith('.json') and fname != 'index.json':
                lang_code = fname.replace('.json', '')
                filepath = os.path.join(dir_path, fname)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self._translations[lang_code] = json.load(f)
                except Exception:
                    self._translations[lang_code] = {}

    def set_language(self, lang_code):
        if lang_code in self._translations:
            self._current_lang = lang_code

    def get_language(self):
        return self._current_lang

    def translate(self, key, default=None):
        translations = self._translations.get(self._current_lang, {})
        if key in translations:
            return translations[key]
        en_translations = self._translations.get('en', {})
        return en_translations.get(key, default if default else key)

    def t(self, key, default=None):
        return self.translate(key, default)

    def get_available_languages(self):
        return list(self._translations.keys())

    def get_translations(self, lang_code=None):
        code = lang_code or self._current_lang
        return self._translations.get(code, {})

    def get_all_translations(self):
        return {lang: data.get('app.name', lang) for lang, data in self._translations.items()}

    def as_dict(self, lang_code=None):
        code = lang_code or self._current_lang
        return self._translations.get(code, {})
