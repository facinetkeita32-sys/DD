/* Dashboard-only presentation. Stored amounts and POS currency logic are untouched. */
const Dashboard = {
  requestId: 0,
  data: null,
  labels: {
    loading: 'Loading metrics…', updated: 'Updated at',
    business: 'Business overview', personal: 'My sales only',
    revenue: 'Revenue', orders: 'Paid orders', average: 'Average order value',
    outstanding: 'Outstanding balance', pending: 'Pending orders from this period',
    compared: 'compared with the previous period', no_baseline: 'No previous reference',
    unchanged: 'No change', revenue_note: 'Paid and completed sales',
    average_note: 'Revenue / paid orders',
    error: 'Unable to load metrics. Check your connection and try again.',
    invalid_dates: 'Choose two valid dates in order, covering at most 366 days and no future dates.',
    scope_error: 'A company reporting scope must be defined before viewing these metrics.',
    currency_error: 'Multiple currencies are configured; these sales cannot be combined.',
    access_error: 'You do not have access to this dashboard.',
    from: 'From', to: 'to', empty_sales: 'No paid sales in this period.',
    chart_detail: 'Select a chart point to display its values.',
    chart_table: 'View chart data', date: 'Date', refresh: 'Refresh',
    product_fallback: 'Archived product', units: 'units sold',
    products: 'Active products', low_stock: 'Low stock', out_stock: 'Out of stock',
    inventory: 'Inventory value', stock_now: 'Current catalogue snapshot · independent of the selected period',
    stock_method: 'Purchase cost, or selling price when no cost is recorded.',
    reference: 'Reference', total: 'Amount', status: 'Status',
    paid: 'Paid', done: 'Completed', pending_status: 'Pending', cancelled: 'Cancelled', refunded: 'Refunded',
    no_orders: 'No orders in this period.', recent_count: 'orders displayed out of',
    recent_limit: 'The 50 most recent orders in the period, excluding drafts.',
  },

  t(key) { return I18n.t('bi.' + key, this.labels[key] || key) },
  locale() { return I18n.currentLang === 'fr' ? 'fr-FR' : 'en-GB' },
  escape(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]))
  },
  number(value, decimals = 0) {
    return Number(value || 0).toLocaleString(this.locale(), {minimumFractionDigits: decimals, maximumFractionDigits: decimals})
  },
  money(value) {
    const c = this.data?.currency || {symbol: 'FG', decimal_places: 0, position: 'before'}
    const amount = this.number(value, c.decimal_places ?? 0)
    return c.position === 'after' ? `${amount} ${c.symbol}` : `${c.symbol} ${amount}`
  },
  date(value, withTime = false) {
    const parsed = new Date(String(value).replace(' ', 'T') + (String(value).length === 10 ? 'T12:00:00' : ''))
    if (Number.isNaN(parsed.getTime())) return '—'
    return parsed.toLocaleString(this.locale(), withTime
      ? {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'}
      : {day: '2-digit', month: 'short', year: 'numeric'})
  },
  icon(name) {
    const paths = {
      revenue: '<path d="M3 18 9 12l4 3 8-10M15 5h6v6M3 22h18"/>',
      orders: '<rect x="5" y="4" width="14" height="18" rx="2"/><path d="M9 4V2h6v2M9 10h6M9 15h6"/>',
      average: '<path d="M3 5h2l3 11h10l3-8H6M9 21h.01M18 21h.01M10 3h8M14 1v4"/>',
      outstanding: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    }
    return `<svg class="bi-icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.orders}</svg>`
  },

  bind(app) {
    document.getElementById('dashboard-refresh').onclick = () => this.render(app)
    document.getElementById('dashboard-retry').onclick = () => this.render(app)
    document.getElementById('dashboard-period').onchange = e => {
      const custom = e.target.value === 'custom'
      document.getElementById('dashboard-custom-dates').hidden = !custom
      document.getElementById('dashboard-from').required = custom
      document.getElementById('dashboard-to').required = custom
      if (!custom) this.render(app)
    }
    document.getElementById('dashboard-filters').onsubmit = e => {
      e.preventDefault()
      this.render(app)
    }
  },

  query() {
    const period = document.getElementById('dashboard-period').value
    const query = new URLSearchParams({period})
    if (period === 'custom') {
      const from = document.getElementById('dashboard-from').value
      const to = document.getElementById('dashboard-to').value
      const days = (Date.parse(to) - Date.parse(from)) / 86400000
      const today = this.data?.server_today || new Date().toLocaleDateString('en-CA')
      if (!from || !to || !Number.isFinite(days) || days < 0 || days >= 366 || to > today) {
        throw new Error(this.t('invalid_dates'))
      }
      query.set('date_from', from)
      query.set('date_to', to)
    }
    return query.toString()
  },

  async render(app) {
    const screen = document.getElementById('screen-dashboard')
    // Other screens already call App.renderDashboard after a sale; do not make
    // their workflow wait for BI queries or fetch hidden financial data.
    if (!screen.classList.contains('active') || !app.user) return
    screen.lang = I18n.currentLang
    document.getElementById('dashboard-refresh').setAttribute('aria-label', this.t('refresh'))
    const id = ++this.requestId
    const user = app.user
    const content = document.getElementById('dashboard-content')
    const error = document.getElementById('dashboard-error')
    const updated = document.getElementById('dashboard-updated')
    const refresh = document.getElementById('dashboard-refresh')
    error.hidden = true
    try {
      const query = this.query()
      this.data = null
      content.hidden = false
      content.setAttribute('aria-busy', 'true')
      refresh.disabled = true
      updated.textContent = this.t('loading')
      document.getElementById('dashboard-range').textContent = ''
      document.getElementById('dashboard-scope').textContent = ''
      document.getElementById('dashboard-cards').innerHTML = Array.from({length: 4}, () =>
        '<div class="bi-kpi bi-skeleton" aria-hidden="true"><span></span><strong></strong><span></span></div>').join('')
      for (const name of ['chart', 'top-products', 'orders']) {
        document.getElementById('dashboard-' + name).innerHTML = '<div class="bi-loading-block bi-skeleton" aria-hidden="true"></div>'
      }
      document.getElementById('dashboard-stock').innerHTML = ''
      document.getElementById('dashboard-empty').hidden = true
      document.getElementById('dashboard-orders-caption').textContent = ''
      const result = await app.api('GET', '/dashboard/analytics?' + query)
      if (id !== this.requestId || app.user !== user) return
      if (!result.success || !result.data) throw new Error(this.t('error'))
      this.data = result.data
      this.draw()
      updated.textContent = `${this.t('updated')} ${new Date(this.data.generated_at).toLocaleTimeString(this.locale(), {hour: '2-digit', minute: '2-digit'})}`
    } catch (e) {
      if (id !== this.requestId || app.user !== user) return
      content.hidden = true
      updated.textContent = ''
      const errorKey = /^Le périmètre/.test(e.message) ? 'scope_error'
        : /^Plusieurs devises/.test(e.message) ? 'currency_error'
        : /^Accès/.test(e.message) ? 'access_error'
        : /^(Choisissez|Veuillez|Période)/.test(e.message) || e.message === this.t('invalid_dates') ? 'invalid_dates' : 'error'
      document.getElementById('dashboard-error-text').textContent = this.t(errorKey)
      error.hidden = false
    } finally {
      if (id === this.requestId) {
        content.setAttribute('aria-busy', 'false')
        refresh.disabled = false
      }
    }
  },

  draw() {
    const d = this.data
    const e = value => this.escape(value)
    document.getElementById('dashboard-range').textContent = `${this.t('from')} ${this.date(d.date_from)} ${this.t('to')} ${this.date(d.date_to)}`
    document.getElementById('dashboard-scope').textContent = this.t(d.scope === 'personal' ? 'personal' : 'business')
    document.getElementById('dashboard-from').value = d.date_from
    document.getElementById('dashboard-to').value = d.date_to
    for (const name of ['dashboard-from', 'dashboard-to']) document.getElementById(name).max = d.server_today
    const notes = {revenue: 'revenue_note', orders: 'revenue_note', average_order: 'average_note', outstanding: 'pending'}
    document.getElementById('dashboard-cards').innerHTML = [
      ['revenue', 'revenue'], ['orders', 'orders'], ['average_order', 'average'], ['outstanding', 'outstanding'],
    ].map(([key, label]) => {
      const change = d.comparison[key].change_percent
      const good = key === 'outstanding' ? change < 0 : change > 0
      const trend = change == null ? this.t('no_baseline') : change === 0 ? this.t('unchanged')
        : `${change > 0 ? '+' : ''}${this.number(change, 1)} %`
      const value = key === 'orders' ? this.number(d.summary[key]) : this.money(d.summary[key])
      return `<article class="bi-kpi"><div class="bi-kpi-top"><span>${e(this.t(label))}</span><span class="bi-kpi-icon bi-tone-${label}">${this.icon(label)}</span></div><strong class="bi-kpi-value">${e(value)}</strong><p class="bi-kpi-note">${e(this.t(notes[key]))}</p><div class="bi-comparison"><span class="${change == null || change === 0 ? 'bi-neutral' : good ? 'bi-positive' : 'bi-negative'}">${e(trend)}</span><span>${e(this.t('compared'))}</span></div></article>`
    }).join('')
    document.getElementById('dashboard-empty').hidden = d.matching_orders !== 0
    this.drawChart()
    this.drawTopProducts()
    this.drawOrders()
    this.drawStock()
  },

  drawChart() {
    const e = value => this.escape(value)
    const series = this.data.series
    const step = Math.max(1, Math.ceil(series.length / 30))
    const buckets = []
    for (let i = 0; i < series.length; i += step) {
      const rows = series.slice(i, i + step)
      buckets.push({from: rows[0].date, to: rows[rows.length - 1].date,
        revenue: rows.reduce((sum, row) => sum + row.revenue, 0),
        orders: rows.reduce((sum, row) => sum + row.orders, 0)})
    }
    const max = Math.max(1, ...buckets.map(row => row.revenue))
    const min = Math.min(0, ...buckets.map(row => row.revenue))
    const y = value => 190 - (value - min) / (max - min) * 160
    const points = buckets.map((row, i) => `${12 + (i + 0.5) * 976 / buckets.length},${y(row.revenue)}`)
    const baseline = y(0)
    const dateLabel = row => row.from === row.to ? this.date(row.from) : `${this.date(row.from)} – ${this.date(row.to)}`
    document.getElementById('dashboard-chart').innerHTML = `
      <div class="bi-chart-scale"><span>${e(this.money(max))}</span><span>${e(this.money(min))}</span></div>
      <div class="bi-chart-plot"><svg viewBox="0 0 1000 220" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="bi-area" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#7c3aed" stop-opacity=".18"/><stop offset="1" stop-color="#7c3aed" stop-opacity=".01"/></linearGradient></defs>${[30, 70, 110, 150, 190].map(v => `<line x1="0" y1="${v}" x2="1000" y2="${v}" class="bi-grid-line"/>`).join('')}<polygon points="${points[0].split(',')[0]},${baseline} ${points.join(' ')} ${points[points.length - 1].split(',')[0]},${baseline}" fill="url(#bi-area)"/><polyline points="${points.join(' ')}" class="bi-chart-line"/>${points.map(point => {const [x, y] = point.split(','); return `<circle cx="${x}" cy="${y}" r="4" class="bi-chart-dot"/>`}).join('')}</svg>
      <div class="bi-chart-targets">${buckets.map((row, i) => `<button type="button" data-point="${i}" aria-pressed="false" aria-label="${e(`${dateLabel(row)} : ${this.money(row.revenue)}, ${this.number(row.orders)} ${this.t('orders').toLowerCase()}`)}"><span class="bi-chart-tooltip">${e(dateLabel(row))}<strong>${e(this.money(row.revenue))}</strong></span></button>`).join('')}</div></div>
      <div class="bi-chart-axis"><span>${e(this.date(series[0].date))}</span><span>${e(this.date(series[series.length - 1].date))}</span></div>
      <p class="bi-chart-detail" id="dashboard-chart-detail" role="status" aria-live="polite">${e(this.t('chart_detail'))}</p>
      <details class="bi-chart-data"><summary>${e(this.t('chart_table'))}</summary><div class="bi-table-scroll"><table><thead><tr><th>${e(this.t('date'))}</th><th>${e(this.t('revenue'))}</th><th>${e(this.t('orders'))}</th></tr></thead><tbody>${series.map(row => `<tr><td>${e(this.date(row.date))}</td><td>${e(this.money(row.revenue))}</td><td>${this.number(row.orders)}</td></tr>`).join('')}</tbody></table></div></details>`
    document.querySelectorAll('#dashboard-chart [data-point]').forEach(button => {
      button.onclick = () => {
        document.querySelectorAll('#dashboard-chart [data-point]').forEach(b => b.setAttribute('aria-pressed', String(b === button)))
        const row = buckets[Number(button.dataset.point)]
        document.getElementById('dashboard-chart-detail').textContent = `${dateLabel(row)} · ${this.money(row.revenue)} · ${this.number(row.orders)} ${this.t('orders').toLowerCase()}`
      }
    })
  },

  drawTopProducts() {
    const e = value => this.escape(value)
    const rows = this.data.top_products
    const max = Math.max(1, ...rows.map(row => Math.abs(row.revenue)))
    document.getElementById('dashboard-top-products').innerHTML = rows.length ? `<ol class="bi-product-list">${rows.map((row, i) => `<li><span class="bi-rank">${i + 1}</span><div class="bi-product-info"><div><strong>${e(row.name || this.t('product_fallback'))}</strong><span>${e(this.money(row.revenue))}</span></div><p>${this.number(row.quantity, Number.isInteger(row.quantity) ? 0 : 3)} ${e(this.t('units'))}</p><div class="bi-product-track"><span style="width:${Math.abs(row.revenue) / max * 100}%"></span></div></div></li>`).join('')}</ol>` : `<div class="bi-panel-empty">${e(this.t('empty_sales'))}</div>`
  },

  drawOrders() {
    const e = value => this.escape(value)
    const rows = this.data.recent_orders
    document.getElementById('dashboard-orders-caption').textContent = `${this.number(rows.length)} ${this.t('recent_count')} ${this.number(this.data.matching_orders)}. ${this.t('recent_limit')}`
    const labels = {paid: 'paid', done: 'done', pending: 'pending_status', cancelled: 'cancelled', refunded: 'refunded'}
    document.getElementById('dashboard-orders').innerHTML = rows.length ? `<div class="bi-table-scroll"><table><thead><tr><th>${e(this.t('reference'))}</th><th>${e(this.t('date'))}</th><th class="text-right">${e(this.t('total'))}</th><th>${e(this.t('status'))}</th></tr></thead><tbody>${rows.map(row => `<tr><td class="bi-order-ref">${e(row.name || '#' + row.id)}</td><td>${e(this.date(row.date_order, true))}</td><td class="text-right bi-order-total">${e(this.money(row.amount_total))}</td><td><span class="bi-status bi-status-${labels[row.state] || 'pending_status'}">${e(this.t(labels[row.state] || 'pending_status'))}</span></td></tr>`).join('')}</tbody></table></div>` : `<div class="bi-panel-empty">${e(this.t('no_orders'))}</div>`
  },

  drawStock() {
    const stock = this.data.stock
    const container = document.getElementById('dashboard-stock')
    if (!stock) { container.innerHTML = ''; return }
    const e = value => this.escape(value)
    const cells = [['products', 'products'], ['low', 'low_stock'], ['out', 'out_stock']]
    container.innerHTML = `<section class="bi-stock"><div class="bi-stock-title">${e(this.t('stock_now'))}</div><div class="bi-stock-grid">${cells.map(([key, label]) => `<div><span>${e(this.t(label))}</span><strong class="${key === 'out' && stock[key] ? 'bi-negative' : ''}">${this.number(stock[key])}</strong></div>`).join('')}${Object.hasOwn(stock, 'inventory_value') ? `<div title="${e(this.t('stock_method'))}"><span>${e(this.t('inventory'))}</span><strong>${e(this.money(stock.inventory_value))}</strong><small>${e(this.t('stock_method'))}</small></div>` : ''}</div></section>`
  },
}
