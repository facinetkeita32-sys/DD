const I18n = {
  translations: {},
  currentLang: 'en',
  requestId: 0,

  async init(lang) {
    this.currentLang = lang || 'en'
    const requestId = ++this.requestId
    try {
      const res = await fetch(`/api/translations/${this.currentLang}`)
      const json = await res.json()
      if (requestId !== this.requestId) return
      if (json.success) this.translations = json.data || {}
    } catch(e) {
      console.warn('i18n init error', e)
    }
    if (requestId === this.requestId) this.apply()
  },

  setLang(lang) {
    this.currentLang = lang
    fetch('/api/settings/language', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lang})
    }).catch(() => {})
    return this.init(lang)
  },

  t(key, def) {
    return this.translations[key] || def || key
  },

  apply() {
    document.documentElement.lang = this.currentLang
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n
      el.textContent = this.t(key, el.textContent)
    })
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.dataset.i18nPlaceholder
      el.placeholder = this.t(key, el.placeholder)
    })
    document.title = this.t('app.name', 'Shop With DD POS')
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
      el.setAttribute('aria-label', this.t(el.dataset.i18nAriaLabel, el.getAttribute('aria-label')))
    })
  }
}
