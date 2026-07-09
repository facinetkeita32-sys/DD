const I18n = {
  translations: {},
  currentLang: 'en',

  async init(lang) {
    this.currentLang = lang || 'en'
    try {
      const res = await fetch(`/api/translations/${this.currentLang}`)
      const json = await res.json()
      if (json.success) this.translations = json.data || {}
    } catch(e) {
      console.warn('i18n init error', e)
    }
    this.apply()
  },

  setLang(lang) {
    this.currentLang = lang
    fetch('/api/settings/language', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lang})
    }).catch(() => {})
    this.init(lang)
  },

  t(key, def) {
    return this.translations[key] || def || key
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
