const I18n = {
  _allTranslations: {},
  currentLang: 'en',

  async init(lang) {
    this.currentLang = lang || 'en'
    this._allTranslations = {}
    const langs = ['en', 'fr']
    await Promise.all(langs.map(code => this._loadLang(code)))
    this.apply()
  },

  async _loadLang(code) {
    if (this._allTranslations[code]) return
    try {
      const res = await fetch(`/api/translations/${code}`)
      const json = await res.json()
      if (json.success) this._allTranslations[code] = json.data || {}
    } catch(e) {
      console.warn('i18n load error', code, e)
    }
  },

  setLang(lang) {
    this.currentLang = lang
    fetch('/api/settings/language', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lang})
    }).catch(() => {})
    this.apply()
  },

  t(key, def) {
    const langData = this._allTranslations[this.currentLang] || {}
    return langData[key] || def || key
  },

  apply() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n
      el.textContent = this.t(key, el.textContent)
    })
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.dataset.i18nPlaceholder
      el.placeholder = this.t(key, el.placeholder)
    })
    document.title = this.t('app.name', 'Shop With DD POS')
  }
}
