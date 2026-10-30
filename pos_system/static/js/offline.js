const Offline = {
  state: null,
  t(key, fallback) { return I18n.t('offline.' + key, fallback || key) },
  async init(app) {
    try {
      const response = await fetch('/api/offline/status')
      if (!response.ok) return null // Older servers retain normal online behavior.
      this.state = (await response.json()).data
      if (!this.state?.local) return null
      app.offlineMode = true
      const setup = document.getElementById('offline-setup')
      document.getElementById('login-box').hidden = !this.state.ready
      setup.hidden = this.state.ready
      setup.onsubmit = async e => {
        e.preventDefault()
        const button = document.getElementById('offline-enroll')
        const message = document.getElementById('offline-setup-message')
        button.disabled = true
        message.textContent = this.t('registering')
        try {
          const result = await app.api('POST', '/offline/enroll', {
            server_url: document.getElementById('offline-server').value,
            device_name: document.getElementById('offline-device').value,
            login: document.getElementById('offline-manager').value,
            password: document.getElementById('offline-password').value,
          })
          document.getElementById('offline-password').value = ''
          document.getElementById('login-user').value = result.data.login
          document.getElementById('login-pass').value = ''
          setup.hidden = true
          document.getElementById('login-box').hidden = false
          this.state.ready = true
          this.paint(app)
        } catch (error) {
          message.textContent = this.t('setup_failed') + ' ' + error.message
        } finally { button.disabled = false }
      }
      document.getElementById('offline-status').onclick = () => this.details(app)
      this.paint(app)
      this.timer = setInterval(() => { if (app.user) this.refresh(app) }, 10000)
      return {needsSetup: !this.state.ready}
    } catch (error) { return null }
  },
  paint(app) {
    if (!this.state?.local) return
    const button = document.getElementById('offline-status')
    button.hidden = !app.user
    const attention = !this.state.connected || this.state.error || this.state.pending
    button.classList.toggle('attention', Boolean(attention))
    const label = this.state.blocked ? this.t('blocked') : this.state.error && this.state.error !== 'network'
      ? this.t('attention') : this.state.connected ? this.t('connected') : this.t('disconnected')
    button.textContent = `${label} · ${this.state.pending || 0} ${this.t('pending')}`
    button.setAttribute('aria-label', button.textContent)
    this.configureManagement(app)
  },
  configureManagement(app) {
    if (!this.state?.local) return
    const escape = value => Dashboard.escape(value)
    for (const screen of ['products', 'settings', 'users']) {
      const target = document.getElementById('screen-' + screen)
      let notice = target.querySelector('.offline-management-notice')
      if (!notice) {
        notice = document.createElement('div')
        notice.className = 'offline-management-notice offline-help'
        target.querySelector('.screen-header').after(notice)
      }
      notice.textContent = this.t(screen === 'users' ? 'users_central' : 'management_hint')
    }
    document.getElementById('add-user-btn').hidden = !app.hasAction('user.create')
    for (const id of ['backup-push-btn', 'backup-restore-btn']) {
      const section = document.getElementById(id).closest('.settings-form')
      section.querySelectorAll('input,button,select').forEach(control => { control.disabled = true })
      let help = section.querySelector('.offline-central-help')
      if (!help) {
        help = document.createElement('p')
        help.className = 'offline-central-help offline-help'
        section.prepend(help)
      }
      help.textContent = this.t('backup_central')
    }
    const section = document.getElementById('offline-management')
    section.hidden = !app.hasScreen('settings')
    if (!section.hidden) {
      const url = this.state.server_url
      document.getElementById('offline-device-list').innerHTML = `<p class="offline-help">${escape(this.t('management_hint'))}</p>${url ? `<a class="btn btn-secondary" target="_blank" rel="noopener noreferrer" href="${escape(url)}">${escape(this.t('open_central'))}</a>` : ''}`
    }
  },
  async refresh(app) {
    if (!app.user || !this.state?.enabled) return
    if (!this.state.local) {
      const section = document.getElementById('offline-management')
      section.hidden = !app.hasScreen('settings')
      if (section.hidden) return
      try {
        const result = await app.api('GET', '/offline/devices')
        const escape = value => Dashboard.escape(value)
        document.getElementById('offline-device-list').innerHTML = result.data.length
          ? result.data.map(row => `<div class="offline-device"><span>${escape(row.name)}</span>${row.active ? `<button type="button" class="btn btn-danger btn-sm" data-revoke="${escape(row.id)}">${escape(this.t('revoke'))}</button>` : `<span>${escape(this.t('revoked'))}</span>`}</div>`).join('')
          : `<p class="offline-help">${escape(this.t('no_devices'))}</p>`
        section.querySelectorAll('[data-revoke]').forEach(button => {
          button.onclick = async () => {
            if (!confirm(this.t('confirm_revoke'))) return
            try { await app.api('POST', `/offline/devices/${button.dataset.revoke}/revoke`, {}); this.refresh(app) }
            catch (error) { alert(error.message) }
          }
        })
      } catch (error) { section.hidden = true }
      return
    }
    try {
      this.state = (await app.api('GET', '/offline/status')).data
      this.paint(app)
    } catch (error) { /* Keep the last known status; local sales do not wait for polling. */ }
  },
  details(app) {
    const escape = value => Dashboard.escape(value)
    const state = this.state
    app.showModal(`<h3>${escape(this.t('terminal_status'))}</h3><p>${escape(state.device_name || '')}</p><p class="offline-help">${escape(this.t('cash_only'))}</p><p class="offline-help">${escape(this.t('pending'))}: ${state.pending || 0}</p>${state.error && state.error !== 'network' ? `<p class="error-message">${escape(this.t('conflict_help'))}</p>` : ''}<div class="btn-group">${state.error === 'catalog_conflict' && (app.hasAction('product.write') || app.hasAction('settings.write')) ? `<button type="button" id="offline-review" class="btn btn-warning">${escape(this.t('review'))}</button>` : ''}<button type="button" id="offline-sync-now" class="btn btn-primary">${escape(this.t('sync_now'))}</button><button type="button" id="offline-status-close" class="btn btn-secondary">${escape(I18n.t('common.close', 'Close'))}</button></div>`)
    const review = document.getElementById('offline-review')
    if (review) review.onclick = () => this.review(app)
    document.getElementById('offline-status-close').onclick = () => app.closeModal()
    document.getElementById('offline-sync-now').onclick = async e => {
      e.target.disabled = true
      try { await app.api('POST', '/offline/sync', {}); await this.refresh(app) }
      catch (error) { alert(this.t('conflict_help')) }
      finally { app.closeModal() }
    }
  },
  async review(app) {
    const escape = value => Dashboard.escape(value)
    try {
      const result = await app.api('GET', '/offline/conflicts')
      const row = result.data[0]
      if (!row) { alert(this.t('no_conflicts')); return }
      const format = value => escape((typeof value === 'object' ? JSON.stringify(value) : String(value)).slice(0, 120))
      app.showModal(`<h3>${escape(this.t('review'))}</h3><p class="offline-help">${escape(row.model)} #${row.local_id} · ${escape(this.t('review_hint'))}</p><div class="table-container"><table><thead><tr><th>${escape(this.t('field'))}</th><th>${escape(this.t('local_value'))}</th><th>${escape(this.t('server_value'))}</th></tr></thead><tbody>${Object.entries(row.values).map(([field, value]) => `<tr><td>${escape(field)}</td><td>${format(value)}</td><td>${row.current ? format(row.current[field]) : '—'}</td></tr>`).join('')}</tbody></table></div>${row.duplicate_barcode ? `<div class="form-group"><label>${escape(I18n.t('product.barcode', 'Barcode'))}</label><input id="offline-conflict-barcode" value="${escape(row.duplicate_barcode)}"></div>` : ''}${row.duplicate_name ? `<div class="form-group"><label>${escape(I18n.t('product.name', 'Name'))}</label><input id="offline-conflict-name" value="${escape(row.duplicate_name)}"></div>` : ''}<div class="btn-group"><button type="button" class="btn btn-primary" id="offline-conflict-retry">${escape(this.t('apply_local'))}</button>${row.action === 'update' ? `<button type="button" class="btn btn-secondary" id="offline-conflict-discard">${escape(this.t('keep_server'))}</button>` : ''}<button type="button" class="btn btn-secondary" id="offline-conflict-close">${escape(I18n.t('common.close', 'Close'))}</button></div>`)
      const resolve = async decision => {
        const values = {}
        for (const field of ['barcode', 'name']) {
          const input = document.getElementById('offline-conflict-' + field)
          if (input) values[field] = input.value.trim()
        }
        try {
          await app.api('POST', `/offline/conflicts/${row.id}/resolve`, {decision, values})
          app.closeModal()
          await app.api('POST', '/offline/sync', {})
          await this.refresh(app)
        } catch (error) { alert(error.message) }
      }
      document.getElementById('offline-conflict-retry').onclick = () => resolve('retry')
      const discard = document.getElementById('offline-conflict-discard')
      if (discard) discard.onclick = () => resolve('discard')
      document.getElementById('offline-conflict-close').onclick = () => app.closeModal()
    } catch (error) { alert(error.message) }
  },
}
