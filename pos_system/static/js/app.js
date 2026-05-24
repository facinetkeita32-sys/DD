let App = {
  user: null,
  permissions: null,
  _newLogoBase64: null,
  config: null,
  currency: null,
  products: [],
  categories: [],
  productCategories: [],
  customers: [],
  paymentMethods: [],
  users: [],
  cart: [],
  cartCustomer: null,
  currentCategory: null,
  session: null,
  company: null,

  async init() {
    await I18n.init('en')
    this.bindEvents()
    this.checkLogin()
  },

  bindEvents() {
    document.getElementById('login-btn').onclick = () => this.doLogin()
    document.getElementById('login-user').onkeydown = e => { if (e.key === 'Enter') this.doLogin() }
    document.getElementById('login-pass').onkeydown = e => { if (e.key === 'Enter') this.doLogin() }
    document.getElementById('login-lang').onchange = e => {
      I18n.setLang(e.target.value)
    }
    document.getElementById('logout-btn').onclick = () => this.doLogout()
    document.getElementById('nav-lang').onchange = e => {
      I18n.setLang(e.target.value)
      this.refreshUI()
    }

    const navLinks = document.getElementById('nav-links')
    const navToggle = document.getElementById('nav-toggle')
    navToggle.onclick = (e) => {
      e.stopPropagation()
      navLinks.classList.toggle('open')
      navToggle.textContent = navLinks.classList.contains('open') ? '✕' : '☰'
    }
    document.addEventListener('click', (e) => {
      if (navLinks.classList.contains('open') && !e.target.closest('#navbar')) {
        navLinks.classList.remove('open')
        navToggle.textContent = '☰'
      }
    })

    document.querySelectorAll('.nav-link').forEach(link => {
      link.onclick = () => {
        navLinks.classList.remove('open')
        this.showScreen(link.dataset.screen)
      }
    })

    document.getElementById('pos-search').oninput = () => this.renderProducts()
    document.getElementById('pos-barcode').onkeydown = e => {
      if (e.key === 'Enter') {
        e.preventDefault()
        this.handleBarcodeScan(e.target.value.trim())
      }
    }
    document.getElementById('pos-barcode').oninput = function() {
      // Auto-submit if barcode length >= 6 (likely a complete scan without Enter)
      const val = this.value.trim()
      if (val.length >= 6 && val.length <= 30) {
        // Small delay to ensure we get the full barcode
        if (this._barcodeTimer) clearTimeout(this._barcodeTimer)
        this._barcodeTimer = setTimeout(() => {
          if (this.value.trim() === val) {
            App.handleBarcodeScan(val)
          }
        }, 150)
      }
    }
    document.getElementById('pay-btn').onclick = () => this.showPaymentModal()
    document.getElementById('cart-clear').onclick = () => this.clearCart()
    const camBtn = document.getElementById('pos-camera-scan')
    if (camBtn) camBtn.onclick = () => this.startScanner()
    const scannerClose = document.getElementById('scanner-close')
    if (scannerClose) scannerClose.onclick = () => this.stopScanner()
    const orderFilter = document.getElementById('order-state-filter')
    if (orderFilter) orderFilter.onchange = () => this.renderOrdersTable()
    document.getElementById('add-product-btn').onclick = () => this.showProductModal()
    document.getElementById('export-products-csv-btn').onclick = () => this.exportProductsCsv()
    document.getElementById('bulk-import-btn').onclick = () => this.showBulkImportModal()
    document.getElementById('manage-cats-btn').onclick = () => this.showCategoryListModal()
    document.getElementById('add-customer-btn').onclick = () => this.showCustomerModal()
    document.getElementById('open-session-btn').onclick = () => this.openSession()
    document.getElementById('generate-report-btn').onclick = () => this.generateReport()
    document.getElementById('export-csv-btn').onclick = () => this.exportReportCsv()
    document.getElementById('settings-save-btn').onclick = () => this.saveSettings()
    document.getElementById('add-user-btn').onclick = () => this.showUserModal()
    document.getElementById('add-delivery-zone-btn').onclick = () => this.showDeliveryZoneModal()
    document.getElementById('settings-logo-area').onclick = () => document.getElementById('settings-logo-input').click()
    document.getElementById('settings-logo-input').onchange = (e) => {
      const file = e.target.files[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = (ev) => {
        this._newLogoBase64 = ev.target.result.split(',')[1]
        document.getElementById('settings-logo-preview').src = ev.target.result
        document.getElementById('settings-logo-preview').style.display = 'block'
        document.getElementById('settings-logo-area').classList.add('has-image')
        document.getElementById('settings-logo-prompt').textContent = I18n.t('settings.change_logo', 'Change Logo')
      }
      reader.readAsDataURL(file)
    }

    document.getElementById('modal-overlay').onclick = e => {
      if (e.target === document.getElementById('modal-overlay')) this.closeModal()
    }
    document.getElementById('scanner-overlay').onclick = e => {
      if (e.target === document.getElementById('scanner-overlay')) this.stopScanner()
    }
  },

  async api(method, path, body) {
    const opts = { method, headers: {'Content-Type': 'application/json'} }
    if (body) opts.body = JSON.stringify(body)
    try {
      const res = await fetch('/api' + path, opts)
      const json = await res.json()
      if (!res.ok) throw new Error(json.error || 'Request failed')
      return json
    } catch(e) {
      if (e.message.includes('401') || e.message.includes('Unauthorized')) {
        this.showLogin()
        throw e
      }
      throw e
    }
  },

  async checkLogin() {
    try {
      const res = await this.api('GET', '/auth/me')
      this.user = res.data
      const permRes = await this.api('GET', '/auth/permissions')
      this.permissions = permRes.data
      document.getElementById('nav-user').textContent = `${this.user.name || this.user.login} (${this.user.role || ''})`
      await this.loadInitData()
      this.showScreen('pos')
      document.getElementById('main-screen').classList.add('active')
      document.getElementById('login-screen').classList.remove('active')
    } catch(e) {
      this.showLogin()
    }
  },

  hasScreen(screen) {
    if (!this.permissions) return false
    return this.permissions.screens.indexOf(screen) !== -1
  },

  hasAction(action) {
    if (!this.permissions) return false
    return this.permissions.actions.indexOf(action) !== -1
  },

  showLogin() {
    document.getElementById('login-screen').classList.add('active')
    document.getElementById('main-screen').classList.remove('active')
  },

  async doLogin() {
    const login = document.getElementById('login-user').value
    const password = document.getElementById('login-pass').value
    const lang = document.getElementById('login-lang').value
    document.getElementById('login-error').textContent = ''
    try {
      const res = await this.api('POST', '/auth/login', { login, password })
      this.user = res.data
      const permRes = await this.api('GET', '/auth/permissions')
      this.permissions = permRes.data
      I18n.setLang(lang)
      document.getElementById('nav-user').textContent = `${this.user.name || this.user.login} (${this.user.role || ''})`
      await this.loadInitData()
      this.showScreen('pos')
      document.getElementById('main-screen').classList.add('active')
      document.getElementById('login-screen').classList.remove('active')
    } catch(e) {
      document.getElementById('login-error').textContent = I18n.t('login.error', 'Invalid credentials')
    }
  },

  async doLogout() {
    await this.api('POST', '/auth/logout')
    this.user = null
    this.showLogin()
  },

  async loadInitData() {
    try {
      const [confRes, curRes, prodRes, catRes, pcatRes, custRes, pmRes, compRes, dzRes] = await Promise.all([
        this.api('GET', '/config'),
        this.api('GET', '/currencies'),
        this.api('GET', '/products'),
        this.api('GET', '/pos-categories'),
        this.api('GET', '/product-categories'),
        this.api('GET', '/customers'),
        this.api('GET', '/payment-methods'),
        this.api('GET', '/company'),
        this.api('GET', '/delivery-zones'),
      ])
      this.config = confRes.data
      this.currencies = curRes.data || []
      this.products = prodRes.data || []
      this.categories = catRes.data || []
      this.productCategories = pcatRes.data || []
      this.customers = custRes.data || []
      this.paymentMethods = pmRes.data || []
      this.company = compRes.data
      this.deliveryZones = dzRes.data || []

      if (this.config && this.config.currency) {
        this.currency = this.config.currency
      }
      this.lowStockThreshold = (this.config && this.config.low_stock_threshold) || 5
      this.ensureDefaultCurrency()
      this.displayLogo(this.company ? this.company.logo : null)
      this.renderAll()
    } catch(e) {
      console.error('loadInitData error', e)
    }
  },

  renderAll() {
    this.applyNavPermissions()
    this.renderProducts()
    this.renderCategories()
    this.renderCart()
    this.renderProductsTable()
    this.renderOrdersTable()
    this.renderCustomersTable()
    this.renderSessionsTable()
    this.renderDashboard()
    this.renderSettings()
    this.renderUsersTable()
  },

  refreshUI() {
    I18n.apply()
    this.renderAll()
  },

  ensureDefaultCurrency() {
    if (this.currency && this.currency.id) return
    const gnf = (this.currencies || []).find(c => c.iso_code === 'GNF')
    if (gnf) {
      this.currency = gnf
    } else {
      this.currency = {
        id: null, symbol: 'FG', decimal_places: 0, position: 'before', name: 'Guinean Franc', iso_code: 'GNF',
      }
    }
  },

  showScreen(name) {
    if (!this.hasScreen(name)) return
    this.applyNavPermissions()
    document.querySelectorAll('.content-screen').forEach(s => s.classList.remove('active'))
    document.getElementById('screen-' + name)?.classList.add('active')
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'))
    document.querySelector(`.nav-link[data-screen="${name}"]`)?.classList.add('active')
    if (name === 'pos') this.refreshAndRenderProducts()
    if (name === 'products') this.refreshAndRenderProducts()
    if (name === 'orders') this.renderOrdersTable()
    if (name === 'customers') this.renderCustomersTable()
    if (name === 'sessions') this.renderSessionsTable()
    if (name === 'dashboard') this.renderDashboard()
    if (name === 'reports') this.generateReport()
    if (name === 'users') this.renderUsersTable()
  },

  applyNavPermissions() {
    document.querySelectorAll('.nav-link').forEach(link => {
      const screen = link.dataset.screen
      if (screen && this.hasScreen(screen)) {
        link.style.display = ''
      } else {
        link.style.display = 'none'
      }
    })
  },

  currencyFormat(amount) {
    const c = this.currency || {}
    const symbol = c.symbol || 'FG'
    const decimals = c.decimal_places != null ? c.decimal_places : 0
    const pos = c.position || 'before'
    const formatted = Number(amount || 0).toFixed(decimals)
    return pos === 'before' ? `${symbol} ${formatted}` : `${formatted} ${symbol}`
  },

  // === POS PRODUCTS ===

  renderCategories() {
    const container = document.getElementById('pos-categories')
    let html = `<button class="pos-cat-btn ${!this.currentCategory ? 'active' : ''}" data-cat-id="">${I18n.t('pos.category_all', 'All')}</button>`
    this.categories.forEach(c => {
      html += `<button class="pos-cat-btn ${this.currentCategory === c.id ? 'active' : ''}" data-cat-id="${c.id}">${c.name}</button>`
    })
    container.innerHTML = html
    container.querySelectorAll('.pos-cat-btn').forEach(btn => {
      btn.onclick = () => {
        this.currentCategory = btn.dataset.catId ? parseInt(btn.dataset.catId) : null
        this.renderCategories()
        this.renderProducts()
      }
    })
  },

  async refreshAndRenderProducts() {
    try {
      const res = await this.api('GET', '/products')
      this.products = res.data || []
    } catch(e) {}
    this.renderProducts()
    this.renderCategories()
  },

  renderProducts() {
    const search = (document.getElementById('pos-search').value || '').toLowerCase()
    let filtered = this.products.filter(p => {
      if (this.currentCategory) {
        const cats = p.pos_categ_ids || []
        if (!cats.includes(this.currentCategory)) return false
      }
      if (search) {
        return (p.name || '').toLowerCase().includes(search) ||
               (p.barcode || '').toLowerCase().includes(search)
      }
      return true
    })
    const grid = document.getElementById('pos-product-grid')
    if (!filtered.length) {
      grid.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-light)">${I18n.t('product.no_products', 'No products')}</div>`
      return
    }
    const threshold = this.lowStockThreshold || 5
    grid.innerHTML = filtered.map((p, idx) => {
      const qty = p.available_qty || 0
      const isLow = qty <= threshold && qty > 0
      const isOut = qty <= 0
      let cls = 'product-card'
      if (isOut) cls += ' out-of-stock'
      else if (isLow) cls += ' low-stock'
      const badge = isOut ? `<span class="stock-badge out">${I18n.t('product.out_of_stock', 'Out')}</span>`
        : isLow ? `<span class="stock-badge low">${I18n.t('product.low_stock', 'Low')}</span>`
        : qty > 0 ? `<span class="stock-badge ok">${I18n.t('product.in_stock', 'In Stock')}</span>` : ''
      const expDate = p.expiration_date || ''
      let expWarn = ''
      if (expDate) {
        const now = new Date()
        const exp = new Date(expDate.substring(0, 10) + 'T00:00:00')
        const diffDays = Math.ceil((exp - now) / (1000 * 60 * 60 * 24))
        if (diffDays < 0) {
          expWarn = `<div class="prod-exp-badge expired">${I18n.t('product.expired', 'Expired')}</div>`
          if (!cls.includes('out-of-stock')) cls += ' expired'
        } else if (diffDays <= 30) {
          expWarn = `<div class="prod-exp-badge expiring">${I18n.t('product.expires_in', 'Expires')} ${diffDays}d</div>`
          cls += ' expiring-soon'
        }
      }
      const catName = p.categ_id ? p.categ_id.name || '' : ''
      const imgHtml = p.image
        ? `<img class="prod-img" src="data:image/png;base64,${p.image}" alt="${p.name}" loading="lazy">`
        : `<div class="prod-img-placeholder">📦</div>`
      return `<div class="${cls}" data-id="${p.id}" style="animation-delay:${(idx % 20) * 20}ms">
        <div class="prod-img-wrap">${imgHtml}</div>
        ${badge}
        ${expWarn}
        <div class="prod-name">${p.name || ''}</div>
        <div class="prod-category">${catName ? this._esc(catName) : ''}</div>
        <div class="prod-price">${this.currencyFormat(p.list_price)}</div>
        <div class="prod-qty">${qty > 0 ? `${qty} ${I18n.t('product.qty', 'in stock')}` : I18n.t('product.out_of_stock', 'Out of stock')}</div>
      </div>`
    }).join('')
    grid.querySelectorAll('.product-card').forEach(card => {
      card.onclick = () => this.addToCart(parseInt(card.dataset.id))
    })
  },

  _normalizeBarcode(code) {
    const c = code.trim()
    if (c.length === 13 && c[0] === '0' && /^\d{13}$/.test(c)) return c.slice(1)
    return c
  },

  handleBarcodeScan(barcode) {
    const input = document.getElementById('pos-barcode')
    if (!barcode) return
    const original = barcode.trim()
    const normal = this._normalizeBarcode(barcode)
    const variants = [original]
    if (normal !== original) variants.push(normal)
    let product = null
    for (const v of variants) {
      product = this.products.find(p => p.barcode && p.barcode.trim() === v)
      if (product) break
    }
    if (product) {
      this.addToCart(product.id)
      this.showBarcodeFeedback(`${product.name} ${I18n.t('pos.added', 'added')}!`, 'success')
      const card = document.querySelector(`.product-card[data-id="${product.id}"]`)
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' })
        card.classList.remove('added-anim')
        void card.offsetWidth
        card.classList.add('added-anim')
      }
    } else {
      this.showBarcodeFeedback(`${I18n.t('product.not_found', 'Product not found')}: ${barcode}`, 'error')
    }
    if (input) { input.value = ''; input.focus() }
  },

  showBarcodeFeedback(message, type) {
    const existing = document.querySelector('.barcode-feedback')
    if (existing) existing.remove()
    const el = document.createElement('div')
    el.className = `barcode-feedback ${type}`
    el.textContent = message
    document.body.appendChild(el)
    setTimeout(() => { el.remove() }, 2000)
  },

  // === CAMERA SCANNER ===

  startScanner(onScan) {
    const overlay = document.getElementById('scanner-overlay')
    const status = document.getElementById('scanner-status')
    const viewport = document.getElementById('scanner-viewport')
    if (!overlay || !viewport) return
    if (this._scannerActive) this.stopScanner()

    const setStatus = (msg, color) => { if (status) { status.textContent = msg; status.style.color = color || '#666' } }
    this._scannerActive = true

    if ('BarcodeDetector' in globalThis) {
      overlay.style.display = 'flex'
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        .then(stream => {
          this._scannerActive = true
          const video = document.createElement('video')
          video.setAttribute('playsinline', '')
          video.style.width = '100%'
          video.style.height = '100%'
          video.style.objectFit = 'cover'
          viewport.innerHTML = ''
          viewport.appendChild(video)
          video.srcObject = stream
          video.onloadedmetadata = () => {
            video.play().catch(() => {})
            setStatus('Camera active', 'green')
          }
          this._scannerStream = stream
          this._scanTimer = setInterval(() => {
            if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) return
            try {
              const c = document.createElement('canvas')
              c.width = Math.min(video.videoWidth, 640)
              c.height = Math.min(video.videoHeight, 480)
              c.getContext('2d').drawImage(video, 0, 0, c.width, c.height)
              new BarcodeDetector({ formats: ['qr_code','ean_13','ean_8','code_128','code_39','upc_a','upc_e','itf','pdf417','aztec','data_matrix','code_93','codabar'] })
                .detect(c).then(b => {
                  if (b && b.length > 0 && this._scannerActive) {
                    this._scannerActive = false
                    if (navigator.vibrate) navigator.vibrate(200)
                    this.stopScanner()
                    const code = b[0].rawValue.trim()
                    const ncode = this._normalizeBarcode(code)
                    if (onScan) onScan(ncode)
                    else { document.getElementById('pos-barcode').value = ncode; this.handleBarcodeScan(ncode) }
                  }
                }).catch(() => {})
            } catch(e) { setStatus('Error: ' + e.message, 'red') }
          }, 500)
        })
        .catch(err => {
          setStatus('Camera denied: ' + err.message, 'red')
          this.showBarcodeFeedback('Camera: ' + err.message, 'error')
        })
    } else if (typeof Quagga !== 'undefined') {
      overlay.style.display = 'flex'
      viewport.innerHTML = ''
      setStatus('Starting scanner...')
      Quagga.init({
        inputStream: { name: 'Live', type: 'LiveStream', target: viewport,
          constraints: { facingMode: 'environment', width: 320, height: 240 },
          area: { top: '25%', bottom: '25%', left: '5%', right: '5%' } },
        decoder: { readers: ['ean_reader','ean_8_reader','code_128_reader','code_39_reader','upc_reader','upc_e_reader','i2of5_reader'],
          locate: true },
        locate: true,
        numOfWorkers: 0,
        locator: { patchSize: 'small', halfSample: true }
      }, err => {
        if (err) { setStatus('Init error: ' + (err.message || err), 'red'); return }
        this._scannerActive = true
        Quagga.start()
        setStatus('Point camera at a barcode', 'green')
        Quagga.onDetected(result => {
          if (!result || !result.codeResult || !this._scannerActive) return
          const code = (result.codeResult.code || '').trim()
          const digits = code.replace(/\D/g, '')
          if (digits.length < 8 || digits.length > 14) return
          this._scannerActive = false
          if (navigator.vibrate) navigator.vibrate(200)
          this.stopScanner()
          const ncode = this._normalizeBarcode(code)
          if (onScan) onScan(ncode)
          else { document.getElementById('pos-barcode').value = ncode; this.handleBarcodeScan(ncode) }
        })
      })
    } else {
      setStatus('No barcode scanner available', 'red')
    }
  },

  stopScanner() {
    if (this._scanTimer) { clearInterval(this._scanTimer); this._scanTimer = null }
    if (this._scannerStream) {
      this._scannerStream.getTracks().forEach(t => t.stop())
      this._scannerStream = null
    }
    try { Quagga.offDetected(); Quagga.stop() } catch(e) {}
    this._scannerActive = false
    const viewport = document.getElementById('scanner-viewport')
    if (viewport) viewport.innerHTML = ''
    const overlay = document.getElementById('scanner-overlay')
    if (overlay) overlay.style.display = 'none'
  },

  // === CART ===

  addToCart(productId) {
    const product = this.products.find(p => p.id === productId)
    if (!product) return
    const existing = this.cart.find(c => c.product_id === productId)
    if (existing) {
      existing.qty += 1
    } else {
      this.cart.push({
        product_id: productId,
        product_name: product.name,
        price_unit: product.list_price,
        qty: 1,
        discount: 0,
      })
    }
    this.renderCart()
    // Brief pulse animation on the clicked card
    const card = document.querySelector(`.product-card[data-id="${productId}"]`)
    if (card) {
      card.classList.remove('added-anim')
      void card.offsetWidth // reflow
      card.classList.add('added-anim')
    }
  },

  removeFromCart(index) {
    this.cart.splice(index, 1)
    this.renderCart()
  },

  updateCartQty(index, qty) {
    qty = parseFloat(qty) || 0
    if (qty <= 0) {
      this.cart.splice(index, 1)
    } else {
      this.cart[index].qty = qty
    }
    this.renderCart()
  },

  clearCart() {
    this.cart = []
    this.cartCustomer = null
    this.selectedDeliveryZone = null
    this.renderCart()
  },

  renderCart() {
    const container = document.getElementById('cart-items')
    const totalEl = document.getElementById('cart-total-amount')
    const customerEl = document.getElementById('cart-customer')

    if (this.cartCustomer) {
      const c = this.customers.find(x => x.id === this.cartCustomer)
      customerEl.innerHTML = `<span class="customer-icon">👤</span> ${c ? c.name : 'Customer'} <span class="customer-hint">${I18n.t('common.change', 'change')}</span>`
    } else {
      customerEl.innerHTML = `<span class="customer-icon">➕</span> ${I18n.t('pos.add_customer', 'Add Customer')}`
    }
    customerEl.onclick = () => this.showCustomerSelectModal()

    const floatEl = document.getElementById('cart-floating')
    if (!this.cart.length) {
      container.innerHTML = `<div class="cart-empty">${I18n.t('pos.empty_cart', 'Cart is empty')}<br><span style="font-size:12px;color:var(--text-light)">${I18n.t('pos.search', 'Click products to add')}</span></div>`
      const totalEl2 = document.getElementById('cart-total-amount')
      if (totalEl2) totalEl2.innerHTML = `<span class="total-amount">${this.currencyFormat(0)}</span>`
      if (floatEl) floatEl.style.display = 'none'
      return
    }

    const DISCOUNT_OPTIONS = [0, 20, 25, 30, 35, 40]
    let subtotal = 0
    container.innerHTML = this.cart.map((item, i) => {
      const lineTotal = item.qty * item.price_unit
      const discAmt = lineTotal * (item.discount || 0) / 100
      const st = lineTotal - discAmt
      subtotal += st
      const discBtns = DISCOUNT_OPTIONS.map(d =>
        `<button class="disc-btn${item.discount === d ? ' active' : ''}" data-discount="${d}" data-index="${i}">${d}%</button>`
      ).join('')
      const discHtml = item.discount > 0
        ? `<div class="cart-item-discounted">${this.currencyFormat(st)} <span class="cart-disc-badge">-${item.discount}%</span></div>`
        : ''
      return `
        <div class="cart-item" style="animation-delay:${i * 30}ms">
          <div class="cart-item-info">
            <div class="cart-item-name">${item.product_name}</div>
            <div class="cart-item-details">${this.currencyFormat(item.price_unit)} &times; ${item.qty} = <strong>${this.currencyFormat(st)}</strong></div>
            ${discHtml}
            <div class="cart-discount-row">
              <span class="disc-label">${I18n.t('pos.discount', 'Disc')}:</span>
              ${discBtns}
            </div>
          </div>
          <div class="cart-item-actions">
            <input type="number" value="${item.qty}" min="0.5" step="0.5" data-index="${i}" class="cart-qty-input">
            <span class="cart-item-remove" data-index="${i}">&times;</span>
          </div>
        </div>
      `
    }).join('')

    const zones = this.deliveryZones || []
    const dzCost = this.selectedDeliveryZone && zones.length
      ? (zones.find(z => z.id === this.selectedDeliveryZone) || {}).cost || 0
      : 0
    const grandTotal = subtotal + dzCost

    let totalHtml = `<span class="total-amount">${this.currencyFormat(subtotal)}</span>`
    if (dzCost > 0) {
      totalHtml = `<div class="total-breakdown">
        <span>${I18n.t('pos.subtotal', 'Subtotal')}: <strong>${this.currencyFormat(subtotal)}</strong></span>
        <span style="font-size:13px;color:var(--text-secondary)">${I18n.t('delivery.cost', 'Delivery')}: <strong>${this.currencyFormat(dzCost)}</strong></span>
      </div>
      <span class="total-amount">${this.currencyFormat(grandTotal)}</span>`
    }
    totalEl.innerHTML = totalHtml

    container.querySelectorAll('.cart-qty-input').forEach(inp => {
      inp.onchange = () => this.updateCartQty(parseInt(inp.dataset.index), inp.value)
    })
    container.querySelectorAll('.cart-item-remove').forEach(el => {
      el.onclick = () => this.removeFromCart(parseInt(el.dataset.index))
    })
    container.querySelectorAll('.disc-btn').forEach(btn => {
      btn.onclick = () => {
        const index = parseInt(btn.dataset.index)
        const discount = parseInt(btn.dataset.discount)
        this.cart[index].discount = discount
        this.renderCart()
      }
    })
    if (floatEl) {
      const isMobile = window.innerWidth <= 768
      if (isMobile) {
        const count = this.cart.reduce((s, i) => s + i.qty, 0)
        document.getElementById('cart-floating-count').textContent = count
        document.getElementById('cart-floating-total').textContent = this.currencyFormat(grandTotal)
        floatEl.style.display = 'flex'
      }
    }
  },

  // === PAYMENT MODAL ===

  showPaymentModal() {
    if (!this.cart.length) return
    const subtotal = this.cart.reduce((sum, item) => {
      const lineTotal = item.qty * item.price_unit
      return sum + lineTotal - (lineTotal * (item.discount || 0) / 100)
    }, 0)

    let cartSummary = this.cart.map(item => {
      const lineTotal = item.qty * item.price_unit
      const discounted = lineTotal * (1 - (item.discount || 0) / 100)
      let badge = item.discount ? `<span class="cart-disc-badge">-${item.discount}%</span>` : ''
      return `<div style="display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border-light)">
        <div style="flex:1;font-size:13px;font-weight:500">${item.product_name}</div>
        <div style="white-space:nowrap;font-size:12px;color:var(--text-secondary)">×${item.qty}</div>
        <div style="white-space:nowrap;font-size:14px;font-weight:700">${this.currencyFormat(discounted)} ${badge}</div>
      </div>`
    }).join('')

    const customerName = this.cartCustomer ? (this.customers.find(c => c.id === this.cartCustomer) || {}).name || '' : ''

    // Delivery section inside modal
    const zones = this.deliveryZones || []
    let deliveryHtml = ''
    if (zones.length) {
      zoneOpts = zones.map(z => `<option value="${z.id}" data-cost="${z.cost}">${z.name} — ${this.currencyFormat(z.cost)}</option>`).join('')
      const prevDz = this.selectedDeliveryZone || ''
      deliveryHtml = `<div class="form-group">
        <label>${I18n.t('delivery.zone', 'Delivery Zone')}</label>
        <select id="modal-delivery-zone"><option value="">${I18n.t('delivery.none', 'No delivery')}</option>${zoneOpts}</select>
        <div id="modal-delivery-contact" style="display:none;margin-top:6px">
          <input type="text" id="modal-contact-name" placeholder="${I18n.t('delivery.contact_name', 'Contact Name')}" style="width:100%;padding:8px;margin-bottom:4px;border:1.5px solid var(--border);border-radius:4px;font-size:13px;box-sizing:border-box">
          <input type="text" id="modal-contact-phone" placeholder="${I18n.t('delivery.contact_phone', 'Contact Phone')}" style="width:100%;padding:8px;border:1.5px solid var(--border);border-radius:4px;font-size:13px;box-sizing:border-box">
        </div>
      </div>`
    }

    let html = `<h3>${I18n.t('payment.title', 'Payment')}</h3>
      <div style="margin-bottom:12px;border:1px solid var(--border-light);border-radius:6px;padding:4px 10px;background:var(--bg)">${cartSummary}</div>
      ${deliveryHtml}
      <div style="text-align:center;font-size:36px;font-weight:800;margin:20px 0;letter-spacing:-0.5px;color:var(--primary)" id="modal-total-display">${this.currencyFormat(subtotal)}</div>
      <div class="form-group">
        <label>${I18n.t('payment.method', 'Payment Method')}</label>
        <select id="payment-method">`
    this.paymentMethods.forEach(pm => {
      html += `<option value="${pm.id}">${pm.name}</option>`
    })
    html += `</select></div>
      <div class="form-group">
        <label>${I18n.t('payment.tendered', 'Amount Tendered')}</label>
        <input type="number" id="payment-tendered" value="${subtotal}" step="100">
      </div>
      <div id="payment-change" style="font-size:20px;font-weight:700;margin:12px 0;text-align:center"></div>
      <div class="btn-group" style="margin-top:20px">
        <button class="btn btn-success btn-lg btn-block" id="payment-confirm" style="padding:16px 28px;font-size:18px">${I18n.t('payment.confirm', 'Confirm Payment')}</button>
        <button class="btn btn-warning btn-lg btn-block" id="payment-pay-later" style="padding:12px 28px;font-size:15px;margin-top:6px">${I18n.t('payment.pay_later', 'Pay Later')}</button>
        <button class="btn btn-secondary btn-lg btn-block" id="payment-cancel">${I18n.t('payment.cancel', 'Cancel')}</button>
      </div>`

    this.showModal(html)

    // Wire up delivery zone in modal
    const dzSelect = document.getElementById('modal-delivery-zone')
    if (dzSelect) {
      if (this.selectedDeliveryZone) dzSelect.value = this.selectedDeliveryZone
      const contactDiv = document.getElementById('modal-delivery-contact')
      if (dzSelect.value) contactDiv.style.display = 'block'
      dzSelect.onchange = () => {
        const sel = dzSelect.value ? parseInt(dzSelect.value) : null
        if (contactDiv) contactDiv.style.display = sel ? 'block' : 'none'
        this.selectedDeliveryZone = sel
        this._updateModalTotal()
      }
    }

    document.getElementById('payment-tendered').oninput = () => {
      this._updateModalChange()
    }
    document.getElementById('payment-tendered').dispatchEvent(new Event('input'))
    document.getElementById('payment-confirm').onclick = () => this.confirmPayment()
    document.getElementById('payment-pay-later').onclick = () => this.payLaterOrder()
    document.getElementById('payment-cancel').onclick = () => this.closeModal()
  },

  _updateModalTotal() {
    const subtotal = this.cart.reduce((sum, item) => {
      const lineTotal = item.qty * item.price_unit
      return sum + lineTotal - (lineTotal * (item.discount || 0) / 100)
    }, 0)
    const dz = this.selectedDeliveryZone ? (this.deliveryZones || []).find(z => z.id === this.selectedDeliveryZone) : null
    const dzCost = dz ? dz.cost : 0
    const total = subtotal + dzCost
    const el = document.getElementById('modal-total-display')
    if (dzCost > 0) {
      el.innerHTML = `${I18n.t('pos.subtotal', 'Subtotal')}: ${this.currencyFormat(subtotal)}<br>
        <span style="font-size:14px;color:var(--text-light)">${I18n.t('delivery.cost', 'Delivery')}: ${this.currencyFormat(dzCost)}</span><br>
        <span style="font-size:32px;font-weight:700">${this.currencyFormat(total)}</span>`
    } else {
      el.textContent = this.currencyFormat(total)
    }
    const te = document.getElementById('payment-tendered')
    if (te) { te.value = total; te.dispatchEvent(new Event('input')) }
  },

  _updateModalChange() {
    const subtotal = this.cart.reduce((sum, item) => {
      const lineTotal = item.qty * item.price_unit
      return sum + lineTotal - (lineTotal * (item.discount || 0) / 100)
    }, 0)
    const dz = this.selectedDeliveryZone ? (this.deliveryZones || []).find(z => z.id === this.selectedDeliveryZone) : null
    const total = subtotal + (dz ? dz.cost : 0)
    const tendered = parseFloat(document.getElementById('payment-tendered').value) || 0
    const change = tendered - total
    document.getElementById('payment-change').textContent = change >= 0
      ? `${I18n.t('payment.change', 'Change')}: ${this.currencyFormat(change)}`
      : `${this.currencyFormat(Math.abs(change))} ${I18n.t('common.remaining', 'remaining')}`
  },

  _getModalTotal() {
    const subtotal = this.cart.reduce((sum, item) => {
      const lineTotal = item.qty * item.price_unit
      return sum + lineTotal - (lineTotal * (item.discount || 0) / 100)
    }, 0)
    const dz = this.selectedDeliveryZone ? (this.deliveryZones || []).find(z => z.id === this.selectedDeliveryZone) : null
    return subtotal + (dz ? dz.cost : 0)
  },

  _getModalDeliveryInfo() {
    const dz = this.selectedDeliveryZone ? (this.deliveryZones || []).find(z => z.id === this.selectedDeliveryZone) : null
    const dzCost = dz ? dz.cost : 0
    const contactName = (document.getElementById('modal-contact-name') || {}).value || ''
    const contactPhone = (document.getElementById('modal-contact-phone') || {}).value || ''
    return { dz, dzCost, contactName, contactPhone }
  },

  async confirmPayment() {
    const total = this._getModalTotal()
    const methodId = parseInt(document.getElementById('payment-method').value)
    const tendered = parseFloat(document.getElementById('payment-tendered').value) || total
    const { dz, dzCost, contactName, contactPhone } = this._getModalDeliveryInfo()
    const lines = this.cart.map(item => ({
      product_id: item.product_id,
      product_name: item.product_name,
      qty: item.qty,
      price_unit: item.price_unit,
      discount: item.discount || 0,
      price_subtotal: (item.qty * item.price_unit) * (1 - (item.discount || 0) / 100),
    }))
    const orderData = {
      lines,
      payments: [{ payment_method_id: methodId, amount: total }],
      partner_id: this.cartCustomer || false,
      amount_total: total,
      delivery_cost: dzCost,
      delivery_contact_name: contactName,
      delivery_contact_phone: contactPhone,
      state: 'paid',
    }
    if (dz) orderData.delivery_zone_id = dz.id
    try {
      const res = await this.api('POST', '/orders', orderData)
      this.closeModal()
      this.clearCart()
      const prodRes = await this.api('GET', '/products')
      this.products = prodRes.data || []
      this.renderProducts()
      this.renderProductsTable()
      this.renderOrdersTable()
      this.renderDashboard()
      alert(`Payment confirmed. Order #${res.data ? res.data.id || res.data.name : ''}`)
    } catch(e) {
      alert('Error: ' + e.message)
    }
  },

  async payLaterOrder() {
    const total = this._getModalTotal()
    const { dz, dzCost, contactName, contactPhone } = this._getModalDeliveryInfo()
    const lines = this.cart.map(item => ({
      product_id: item.product_id,
      product_name: item.product_name,
      qty: item.qty,
      price_unit: item.price_unit,
      discount: item.discount || 0,
      price_subtotal: (item.qty * item.price_unit) * (1 - (item.discount || 0) / 100),
    }))

    const orderData = {
      lines,
      payments: [],
      partner_id: this.cartCustomer || false,
      amount_total: total,
      delivery_cost: dzCost,
      delivery_contact_name: contactName,
      delivery_contact_phone: contactPhone,
      state: 'pending',
    }
    if (dz) orderData.delivery_zone_id = dz.id

    try {
      const res = await this.api('POST', '/orders', orderData)
      this.closeModal()
      this.clearCart()
      const prodRes = await this.api('GET', '/products')
      this.products = prodRes.data || []
      this.renderProducts()
      this.renderProductsTable()
      this.renderOrdersTable()
      this.renderDashboard()
      alert(`${I18n.t('payment.pending_saved', 'Order saved as pending payment')}. #${res.data ? res.data.id || res.data.name : ''}`)
    } catch(e) {
      alert('Error: ' + e.message)
    }
  },

  async validatePayment(orderId) {
    if (!confirm(I18n.t('payment.confirm_validate', 'Validate payment for this order?'))) return
    const paymentMethods = this.paymentMethods || []
    let methodHtml = paymentMethods.map(pm =>
      `<option value="${pm.id}">${pm.name}</option>`
    ).join('')
    let html = `<h3>${I18n.t('payment.validate_title', 'Validate Payment')}</h3>
      <div class="form-group">
        <label>${I18n.t('payment.method', 'Payment Method')}</label>
        <select id="validate-payment-method">${methodHtml}</select>
      </div>
      <div class="btn-group" style="margin-top:16px">
        <button class="btn btn-success" id="validate-confirm">${I18n.t('common.confirm', 'Confirm')}</button>
        <button class="btn btn-secondary" id="validate-cancel">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)
    document.getElementById('validate-confirm').onclick = async () => {
      const methodId = parseInt(document.getElementById('validate-payment-method').value)
      try {
        await this.api('POST', `/orders/${orderId}/validate-payment`, {
          payment_method_id: methodId,
        })
        this.closeModal()
        await this.renderOrdersTable()
        this.renderDashboard()
        alert(I18n.t('payment.validated', 'Payment validated'))
      } catch(e) {
        alert('Error: ' + e.message)
      }
    }
    document.getElementById('validate-cancel').onclick = () => this.closeModal()
  },

  // === CUSTOMER SELECT ===

  showCustomerSelectModal() {
    let html = `<h3>${I18n.t('pos.set_customer', 'Set Customer')}</h3>
      <div class="form-group">
        <input type="text" id="customer-search-input" placeholder="${I18n.t('common.search', 'Search')}..." style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px">
      </div>
      <div style="max-height:300px;overflow-y:auto">`
    this.customers.forEach(c => {
      html += `<div class="customer-option" data-id="${c.id}" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border);border-radius:4px">${c.name} ${c.phone ? '- ' + c.phone : ''}</div>`
    })
    html += `</div>
      <div class="btn-group" style="margin-top:12px">
        <button class="btn btn-secondary" id="customer-clear">${I18n.t('pos.remove', 'Remove')}</button>
        <button class="btn btn-secondary" id="customer-cancel-btn">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`

    this.showModal(html)
    document.getElementById('customer-search-input').oninput = () => {
      const q = document.getElementById('customer-search-input').value.toLowerCase()
      document.querySelectorAll('.customer-option').forEach(el => {
        el.style.display = el.textContent.toLowerCase().includes(q) ? 'block' : 'none'
      })
    }
    document.querySelectorAll('.customer-option').forEach(el => {
      el.onclick = () => {
        this.cartCustomer = parseInt(el.dataset.id)
        this.closeModal()
        this.renderCart()
      }
    })
    document.getElementById('customer-clear').onclick = () => {
      this.cartCustomer = null
      this.closeModal()
      this.renderCart()
    }
    document.getElementById('customer-cancel-btn').onclick = () => this.closeModal()
  },

  // === PRODUCTS TABLE ===

  renderProductsTable() {
    const tbody = document.getElementById('products-tbody')
    if (!this.products.length) {
      tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:24px;color:var(--text-light)">${I18n.t('product.no_products', 'No products')}</td></tr>`
      return
    }
    const threshold = this.lowStockThreshold || 5
    const canEdit = this.hasAction('product.write')
    const canDelete = this.hasAction('product.delete')
    tbody.innerHTML = this.products.map(p => {
      const qty = p.available_qty || 0
      const isLow = qty <= threshold && qty > 0
      const isOut = qty <= 0
      let stockHtml = ''
      if (isOut) stockHtml = `<span class="stock-badge out">${I18n.t('product.out_of_stock', 'Out')}</span>`
      else if (isLow) stockHtml = `<span class="stock-badge low">${I18n.t('product.low_stock', 'Low')}</span>`
      else stockHtml = `<span class="stock-badge ok">${I18n.t('product.in_stock', 'In Stock')}</span>`
      const rowCls = isOut ? 'row-out-of-stock' : isLow ? 'row-low-stock' : ''
      const expDate = p.expiration_date || ''
      let expHtml = '-'
      let expCls = ''
      if (expDate) {
        const now = new Date()
        const exp = new Date(expDate + 'T00:00:00')
        const diffDays = Math.ceil((exp - now) / (1000 * 60 * 60 * 24))
        if (diffDays < 0) {
          expHtml = `<span class="stock-badge out" style="font-weight:700">${I18n.t('product.expired', 'Expired')}</span>`
          expCls = ' row-expired'
        } else if (diffDays <= 30) {
          expHtml = `<span class="stock-badge low">${expDate.substring(0, 10)} (${diffDays}d)</span>`
          expCls = ' row-expiring'
        } else {
          expHtml = expDate.substring(0, 10)
        }
      }
      return `<tr class="${rowCls + expCls}">
        <td>${p.image ? `<img class="prod-table-img" src="data:image/png;base64,${p.image}" alt="">` : `<span class="prod-table-img-placeholder">📦</span>`}</td>
        <td>${p.name || ''}</td>
        <td>${this.currencyFormat(p.list_price)}</td>
        <td>${this.currencyFormat(p.cost_price)}</td>
        <td>${qty}</td>
        <td>${stockHtml}</td>
        <td>${expHtml}</td>
        <td>${p.categ_id ? (p.categ_id.name || '') : ''}</td>
        <td>${p.barcode || ''}</td>
        <td>${canEdit ? `<button class="btn btn-sm btn-primary edit-product" data-id="${p.id}">${I18n.t('common.edit', 'Edit')}</button>` : '-'}</td>
        <td>${canDelete ? `<button class="btn btn-sm btn-danger delete-product" data-id="${p.id}">${I18n.t('common.delete', 'Delete')}</button>` : '-'}</td>
      </tr>`
    }).join('')
    tbody.querySelectorAll('.edit-product').forEach(btn => {
      btn.onclick = () => this.showProductModal(parseInt(btn.dataset.id))
    })
    tbody.querySelectorAll('.delete-product').forEach(btn => {
      btn.onclick = () => this.deleteProduct(parseInt(btn.dataset.id))
    })
    const headerActions = document.querySelector('#screen-products .screen-header .btn-group')
    if (headerActions) {
      headerActions.querySelectorAll('button').forEach(b => b.style.display = '')
      if (!canEdit || !this.hasAction('bulk.import')) {
        const bulkBtn = document.getElementById('bulk-import-btn')
        if (bulkBtn) bulkBtn.style.display = 'none'
      }
      if (!this.hasAction('product.create')) {
        const addBtn = document.getElementById('add-product-btn')
        if (addBtn) addBtn.style.display = 'none'
      }
    }
  },

  showProductModal(id) {
    const product = id ? this.products.find(p => p.id === id) : null
    const title = product ? I18n.t('product.edit', 'Edit Product') : I18n.t('product.add', 'Add Product')
    const existingImg = product ? (product.image || '') : ''
    const cats = this.productCategories || []
    const catOpts = cats.map(c => `<option value="${c.id}" ${product && product.categ_id && product.categ_id.id === c.id ? 'selected' : ''}>${this._esc(c.name)}</option>`).join('')
    let html = `<h3>${title}</h3>
      <div class="form-group"><label data-i18n="product.name">Name</label><input id="prod-name" value="${product ? this._esc(product.name || '') : ''}"></div>
      <div class="form-group"><label data-i18n="product.category">Category</label>
        <select id="prod-category"><option value="">${I18n.t('common.none', 'None')}</option>${catOpts}</select>
        <button class="btn btn-sm btn-secondary" id="prod-add-cat" style="margin-top:4px" data-i18n="category.add">+ Add Category</button>
      </div>
      <div class="form-group"><label data-i18n="product.price">Price</label><input id="prod-price" type="number" step="100" value="${product ? product.list_price || 0 : 0}"></div>
      <div class="form-group"><label data-i18n="product.cost">Cost</label><input id="prod-cost" type="number" step="100" value="${product ? product.cost_price || 0 : 0}"></div>
      <div class="form-group"><label data-i18n="product.qty">Quantity</label><input id="prod-qty" type="number" step="1" value="${product ? product.available_qty || 0 : 0}"></div>
      <div class="form-group"><label data-i18n="product.barcode">Barcode</label>
        <div style="display:flex;gap:6px">
          <input id="prod-barcode" style="flex:1" value="${product ? this._esc(product.barcode || '') : ''}">
          <button class="btn btn-sm btn-primary" id="prod-barcode-scan" title="Scan barcode">📷</button>
        </div>
      </div>
      <div class="form-group"><label data-i18n="product.expiration">Expiration Date</label><input id="prod-expiration" type="date" value="${product ? (product.expiration_date || '').substring(0, 10) : ''}"></div>
      <div class="form-group">
        <label data-i18n="product.image">Image</label>
        <div class="image-upload-area ${existingImg ? 'has-image' : ''}" id="image-upload-area">
          <div id="image-upload-prompt">${I18n.t('product.upload_image', 'Upload Image')}</div>
          <img id="image-preview" class="image-preview" style="${existingImg ? 'display:block' : 'display:none'}" src="${existingImg ? 'data:image/png;base64,' + existingImg : ''}">
          <input type="file" id="image-file-input" accept="image/*" style="display:none">
          <input type="file" id="image-camera-input" accept="image/*" capture="environment" style="display:none">
        </div>
        <div class="btn-group" style="margin-top:6px">
          <button class="btn btn-sm btn-secondary" id="image-upload-btn">${I18n.t('product.upload', 'Gallery')}</button>
          <button class="btn btn-sm btn-primary" id="image-camera-btn">📷 ${I18n.t('product.camera', 'Camera')}</button>
          ${existingImg ? `<button class="btn btn-sm btn-danger" id="remove-image-btn">${I18n.t('common.delete', 'Remove')}</button>` : ''}
        </div>
      </div>
      <div class="btn-group">
        <button class="btn btn-primary" id="prod-save">${I18n.t('common.save', 'Save')}</button>
        <button class="btn btn-secondary" id="prod-cancel">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)
    let newImageBase64 = existingImg

    const readFile = (file) => {
      if (!file) return
      const reader = new FileReader()
      reader.onload = (ev) => {
        const base64 = ev.target.result.split(',')[1]
        newImageBase64 = base64
        document.getElementById('image-preview').src = ev.target.result
        document.getElementById('image-preview').style.display = 'block'
        document.getElementById('image-upload-area').classList.add('has-image')
        document.getElementById('image-upload-prompt').textContent = I18n.t('product.upload_image', 'Change Image')
      }
      reader.readAsDataURL(file)
    }

    document.getElementById('image-upload-btn').onclick = () => document.getElementById('image-file-input').click()
    document.getElementById('image-file-input').onchange = (e) => readFile(e.target.files[0])

    document.getElementById('image-camera-btn').onclick = () => document.getElementById('image-camera-input').click()
    document.getElementById('image-camera-input').onchange = (e) => readFile(e.target.files[0])

    const barcodeScanBtn = document.getElementById('prod-barcode-scan')
    if (barcodeScanBtn) {
      barcodeScanBtn.onclick = () => {
        this.startScanner((barcode) => {
          document.getElementById('prod-barcode').value = barcode
        })
      }
    }

    const removeBtn = document.getElementById('remove-image-btn')
    if (removeBtn) {
      removeBtn.onclick = () => {
        newImageBase64 = ''
        document.getElementById('image-preview').style.display = 'none'
        document.getElementById('image-upload-area').classList.remove('has-image')
        document.getElementById('image-upload-prompt').textContent = I18n.t('product.upload_image', 'Upload Image')
        document.getElementById('image-file-input').value = ''
        removeBtn.style.display = 'none'
      }
    }

    document.getElementById('prod-add-cat').onclick = () => this.showCategoryModal()

    document.getElementById('prod-save').onclick = async () => {
      const catVal = document.getElementById('prod-category').value
      const data = {
        name: document.getElementById('prod-name').value,
        list_price: parseFloat(document.getElementById('prod-price').value) || 0,
        cost_price: parseFloat(document.getElementById('prod-cost').value) || 0,
        available_qty: parseFloat(document.getElementById('prod-qty').value) || 0,
        barcode: document.getElementById('prod-barcode').value,
        expiration_date: document.getElementById('prod-expiration').value || false,
      }
      if (catVal) data.categ_id = parseInt(catVal)
      if (newImageBase64 !== undefined) {
        data.image = newImageBase64
      }
      try {
        if (product) {
          await this.api('PUT', `/products/${product.id}`, data)
        } else {
          await this.api('POST', '/products', data)
        }
        this.closeModal()
        const res = await this.api('GET', '/products')
        this.products = res.data || []
        this.renderAll()
      } catch(e) { alert('Error: ' + e.message) }
    }
    document.getElementById('prod-cancel').onclick = () => this.closeModal()
  },

  _esc(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  },

  // === BULK IMPORT ===

  showBulkImportModal() {
    const csvTemplate = 'Name,Price,Cost,Qty,Barcode,Category,Description\nCoffee,5000,2000,100,590001,Beverages,Hot coffee\nTea,4000,1500,100,590003,Beverages,Green tea'
    let html = `<h3>${I18n.t('product.import_title', 'Bulk Import Products')}</h3>
      <p style="font-size:13px;color:var(--text-light);margin-bottom:12px">Upload a CSV file or paste JSON array.</p>
      <div class="form-group">
        <label>CSV File</label>
        <div class="image-upload-area" id="csv-upload-area">
          <div id="csv-upload-prompt">${I18n.t('product.import_csv', 'Import from CSV')}</div>
          <div id="csv-filename" style="font-size:12px;color:var(--success);margin-top:4px"></div>
          <input type="file" id="csv-file-input" accept=".csv,.txt" style="display:none">
        </div>
      </div>
      <div style="text-align:center;font-size:12px;color:var(--text-light);margin:8px 0">${I18n.t('common.or', '- or -')}</div>
      <div class="form-group">
        <label>JSON</label>
        <textarea id="import-json" rows="6" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:monospace;font-size:12px" placeholder='[{"name":"Product","price":5000,"qty":10}]'></textarea>
      </div>
      <div class="btn-group" style="margin-bottom:12px">
        <button class="btn btn-sm btn-secondary" id="download-template-btn">${I18n.t('product.download_template', 'Download CSV Template')}</button>
      </div>
      <div id="import-result" style="display:none;padding:12px;border-radius:6px;margin-bottom:12px"></div>
      <div class="btn-group">
        <button class="btn btn-primary" id="import-exec-btn">${I18n.t('common.save', 'Import')}</button>
        <button class="btn btn-secondary" id="import-cancel-btn">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)

    let csvFile = null
    document.getElementById('csv-upload-area').onclick = () => document.getElementById('csv-file-input').click()
    document.getElementById('csv-file-input').onchange = (e) => {
      csvFile = e.target.files[0]
      if (csvFile) {
        document.getElementById('csv-filename').textContent = `✓ ${csvFile.name}`
        document.getElementById('csv-upload-area').classList.add('has-image')
        document.getElementById('csv-upload-prompt').textContent = I18n.t('product.import_csv', 'Change File')
      }
    }

    document.getElementById('download-template-btn').onclick = () => {
      const blob = new Blob([csvTemplate], {type: 'text/csv'})
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'product_template.csv'; a.click()
      URL.revokeObjectURL(url)
    }

    document.getElementById('import-exec-btn').onclick = async () => {
      const resultDiv = document.getElementById('import-result')
      resultDiv.style.display = 'none'
      try {
        let res
        if (csvFile) {
          const formData = new FormData()
          formData.append('file', csvFile)
          const fetchRes = await fetch('/api/products/bulk-import', { method: 'POST', body: formData })
          res = await fetchRes.json()
          if (!fetchRes.ok) throw new Error(res.error || 'Import failed')
        } else {
          const jsonText = document.getElementById('import-json').value.trim()
          if (!jsonText) { alert('Provide CSV file or JSON data'); return }
          const jsonData = JSON.parse(jsonText)
          res = await this.api('POST', '/products/bulk-import', jsonData)
        }
        const d = res.data || {}
        resultDiv.style.display = 'block'
        resultDiv.className = d.errors && d.errors.length ? 'session-status opened' : 'session-status closed'
        resultDiv.innerHTML = `
          <strong>${I18n.t('product.import_result', 'Result')}:</strong><br>
          ${I18n.t('product.import_created', 'Created')}: ${d.created || 0}<br>
          ${I18n.t('product.import_updated', 'Updated')}: ${d.updated || 0}<br>
          ${I18n.t('product.import_errors', 'Errors')}: ${(d.errors || []).length}
          ${(d.errors || []).length ? '<br><small>' + d.errors.slice(0, 5).join('<br>') + '</small>' : ''}
        `
        const prodRes = await this.api('GET', '/products')
        this.products = prodRes.data || []
        this.renderAll()
      } catch(e) {
        resultDiv.style.display = 'block'
        resultDiv.className = 'session-status closed'
        resultDiv.textContent = 'Error: ' + e.message
      }
    }
    document.getElementById('import-cancel-btn').onclick = () => this.closeModal()
  },

  async deleteProduct(id) {
    if (!confirm(I18n.t('common.confirm', 'Confirm') + '?')) return
    await this.api('DELETE', `/products/${id}`)
    this.products = this.products.filter(p => p.id !== id)
    this.renderAll()
  },

  // === ORDERS TABLE ===

  async renderOrdersTable() {
    try {
      const filterEl = document.getElementById('order-state-filter')
      const stateFilter = filterEl ? filterEl.value : ''
      let url = '/orders'
      if (stateFilter) url += `?status=${stateFilter}`
      const res = await this.api('GET', url)
      const orders = res.data || []
      const tbody = document.getElementById('orders-tbody')
      if (!orders.length) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:24px;color:var(--text-light)">${I18n.t('order.no_orders', 'No orders')}</td></tr>`
        return
      }
      tbody.innerHTML = orders.map(o => {
        const items = (o.lines || []).map(l =>
          `${l.product_name || 'Product'} x${l.qty}`
        ).join(', ') || '-'
        const isPending = o.state === 'pending'
        const validateBtn = isPending
          ? `<button class="btn btn-sm btn-success validate-payment" data-id="${o.id}">${I18n.t('order.validate', 'Validate')}</button>`
          : ''
        return `<tr>
          <td>${o.name || o.id}</td>
          <td>${(o.date_order || '').substring(0, 19)}</td>
          <td>${o.partner_name || '-'}</td>
          <td>${o.user_name || ''}</td>
          <td style="max-width:200px;white-space:normal">${items}</td>
          <td>${this.currencyFormat(o.amount_total)}</td>
          <td><span class="status-badge status-${o.state}">${o.state}</span></td>
          <td>${validateBtn}</td>
          <td><button class="btn btn-sm btn-primary view-order" data-id="${o.id}">${I18n.t('common.edit', 'View')}</button></td>
        </tr>`
      }).join('')
      tbody.querySelectorAll('.view-order').forEach(btn => {
        btn.onclick = () => this.showOrderDetail(parseInt(btn.dataset.id))
      })
      tbody.querySelectorAll('.validate-payment').forEach(btn => {
        btn.onclick = () => this.validatePayment(parseInt(btn.dataset.id))
      })
    } catch(e) { console.error(e) }
  },

  async showOrderDetail(id) {
    try {
      const res = await this.api('GET', `/orders/${id}`)
      const o = res.data
      let itemsHtml = o.lines ? o.lines.map(l =>
        `<tr><td>${l.product_name || 'Product'}</td><td>${l.qty}</td><td>${this.currencyFormat(l.price_unit)}</td><td>${l.discount || 0}%</td><td>${this.currencyFormat(l.price_subtotal || (l.qty * l.price_unit))}</td></tr>`
      ).join('') : ''

      let paymentsHtml = (o.payments || []).map(p =>
        `<tr><td>${p.payment_method_name || 'Payment'}</td><td>${this.currencyFormat(p.amount)}</td></tr>`
      ).join('')

      let dzHtml = ''
      if (o.delivery_cost && parseFloat(o.delivery_cost) > 0) {
        dzHtml = `<div style="margin:8px 0;font-size:13px"><strong>${I18n.t('delivery.zone', 'Delivery')}:</strong> ${o.delivery_zone_name || ''} - ${this.currencyFormat(o.delivery_cost)}</div>`
        if (o.delivery_contact_name || o.delivery_contact_phone) {
          dzHtml += `<div style="font-size:12px;color:var(--text-light);margin-top:2px">`
          if (o.delivery_contact_name) dzHtml += `${I18n.t('common.name', 'Name')}: ${o.delivery_contact_name}`
          if (o.delivery_contact_name && o.delivery_contact_phone) dzHtml += ' | '
          if (o.delivery_contact_phone) dzHtml += `${I18n.t('customer.phone', 'Phone')}: ${o.delivery_contact_phone}`
          dzHtml += `</div>`
        }
      }

      let html = `<h3>${I18n.t('order.details', 'Order Details')}</h3>
        <div class="order-detail-grid">
          <div><span class="label">${I18n.t('order.ref', 'Order #')}</span><div class="value">${o.name || o.id}</div></div>
          <div><span class="label">${I18n.t('order.date', 'Date')}</span><div class="value">${(o.date_order || '').substring(0, 19)}</div></div>
          <div><span class="label">${I18n.t('order.customer', 'Customer')}</span><div class="value">${o.partner_name || '-'}</div></div>
          <div><span class="label">${I18n.t('order.status', 'Status')}</span><div class="value"><span class="status-badge status-${o.state}">${o.state}</span></div></div>
        </div>
        <table style="width:100%;margin:12px 0">
          <thead><tr><th>${I18n.t('product.name', 'Product')}</th><th>${I18n.t('pos.qty', 'Qty')}</th><th>${I18n.t('pos.price', 'Price')}</th><th>${I18n.t('pos.discount', 'Disc')}</th><th>${I18n.t('pos.subtotal', 'Subtotal')}</th></tr></thead>
          <tbody>${itemsHtml}</tbody>
          <tfoot><tr><td colspan="4" style="text-align:right;font-weight:700">${I18n.t('pos.total', 'Total')}:</td><td style="font-weight:700">${this.currencyFormat(o.amount_total)}</td></tr></tfoot>
        </table>
        ${dzHtml}`
      if (paymentsHtml) {
        html += `<table style="width:100%;margin:8px 0">
          <thead><tr><th>${I18n.t('receipt.payment', 'Payment')}</th><th style="text-align:right">${I18n.t('payment.amount', 'Amount')}</th></tr></thead>
          <tbody>${paymentsHtml}</tbody>
        </table>`
      }
      html += `<div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-primary" onclick="App.openPrintReceipt(${id})">${I18n.t('receipt.print', 'Print Receipt')}</button>
        <button class="btn btn-success" onclick="App.downloadReceiptPdf(${id})">${I18n.t('receipt.pdf', 'Download PDF')}</button>
        <button class="btn btn-secondary" onclick="App.closeModal()">${I18n.t('common.close', 'Close')}</button>
      </div>`
      this.showModal(html)
    } catch(e) { alert('Error: ' + e.message) }
  },

  openPrintReceipt(id) {
    window.open(`/api/receipt/${id}/html`, '_blank', 'width=500,height=700,menubar=no,toolbar=no,scrollbars=yes')
  },

  downloadReceiptPdf(id) {
    const a = document.createElement('a')
    a.href = `/api/receipt/${id}/pdf`
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  },

  // === CUSTOMERS TABLE ===

  renderCustomersTable() {
    const tbody = document.getElementById('customers-tbody')
    if (!this.customers.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--text-light)">${I18n.t('customer.title', 'No customers')}</td></tr>`
      return
    }
    tbody.innerHTML = this.customers.map(c => `
      <tr>
        <td>${c.name || ''}</td>
        <td>${c.phone || '-'}</td>
        <td>${c.email || '-'}</td>
        <td>${this.currencyFormat(c.total_due || 0)}</td>
        <td><button class="btn btn-sm btn-primary edit-customer" data-id="${c.id}">${I18n.t('common.edit', 'Edit')}</button></td>
      </tr>
    `).join('')
    tbody.querySelectorAll('.edit-customer').forEach(btn => {
      btn.onclick = () => this.showCustomerModal(parseInt(btn.dataset.id))
    })
  },

  showCustomerModal(id) {
    const customer = id ? this.customers.find(c => c.id === id) : null
    const title = customer ? I18n.t('customer.edit', 'Edit Customer') : I18n.t('customer.add', 'Add Customer')
    let html = `<h3>${title}</h3>
      <div class="form-group"><label data-i18n="customer.name">Name</label><input id="c-name" value="${customer ? customer.name || '' : ''}"></div>
      <div class="form-group"><label data-i18n="customer.phone">Phone</label><input id="c-phone" value="${customer ? customer.phone || '' : ''}"></div>
      <div class="form-group"><label data-i18n="customer.email">Email</label><input id="c-email" value="${customer ? customer.email || '' : ''}"></div>
      <div class="btn-group">
        <button class="btn btn-primary" id="c-save">${I18n.t('common.save', 'Save')}</button>
        <button class="btn btn-secondary" id="c-cancel">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)
    document.getElementById('c-save').onclick = async () => {
      const data = {
        name: document.getElementById('c-name').value,
        phone: document.getElementById('c-phone').value,
        email: document.getElementById('c-email').value,
      }
      try {
        if (customer) {
          await this.api('PUT', `/customers/${customer.id}`, data)
        } else {
          await this.api('POST', '/customers', data)
        }
        this.closeModal()
        const res = await this.api('GET', '/customers')
        this.customers = res.data || []
        this.renderAll()
      } catch(e) { alert('Error: ' + e.message) }
    }
    document.getElementById('c-cancel').onclick = () => this.closeModal()
  },

  // === SESSIONS ===

  async renderSessionsTable() {
    try {
      const res = await this.api('GET', '/sessions')
      const sessions = res.data || []
      const tbody = document.getElementById('sessions-tbody')
      tbody.innerHTML = sessions.map(s => `
        <tr>
          <td>${s.name || s.id}</td>
          <td>${s.user_name || ''}</td>
          <td>${this.currencyFormat(s.cash_register_balance_start || 0)}</td>
          <td>${this.currencyFormat(s.cash_register_balance_end || 0)}</td>
          <td>${this.currencyFormat(s.total_sales || 0)}</td>
          <td>${s.total_orders || 0}</td>
          <td><span class="status-badge status-${s.state}">${s.state}</span></td>
          <td>${s.state === 'opened' ? `<button class="btn btn-sm btn-warning close-session" data-id="${s.id}">${I18n.t('session.close', 'Close')}</button>` : '-'}</td>
        </tr>
      `).join('')

      tbody.querySelectorAll('.close-session').forEach(btn => {
        btn.onclick = () => this.closeSession(parseInt(btn.dataset.id))
      })

      const status = document.getElementById('session-status')
      const openSession = sessions.find(s => s.state === 'opened')
      const canOpen = this.hasAction('session.open')
      const canClose = this.hasAction('session.close')
      if (openSession) {
        status.className = 'session-status opened'
        status.textContent = `✅ ${I18n.t('dashboard.session_opened', 'Session Open')} - ${openSession.name}`
        document.getElementById('open-session-btn').style.display = 'none'
      } else {
        status.className = 'session-status closed'
        status.textContent = `🔴 ${I18n.t('dashboard.session_closed', 'Session Closed')}`
        document.getElementById('open-session-btn').style.display = canOpen ? '' : 'none'
      }
      tbody.querySelectorAll('.close-session').forEach(btn => {
        btn.style.display = canClose ? '' : 'none'
      })
      if (!canOpen) document.getElementById('open-session-btn').style.display = 'none'
    } catch(e) { console.error(e) }
  },

  async openSession() {
    const cash = prompt(I18n.t('session.start_cash', 'Opening Cash amount:'), '0')
    if (cash === null) return
    try {
      await this.api('POST', '/sessions', {
        cash_register_balance_start: parseFloat(cash) || 0,
      })
      const sesRes = await this.api('GET', '/sessions')
      const sessions = sesRes.data || []
      const latest = sessions[0]
      if (latest) {
        await this.api('POST', `/sessions/${latest.id}/open`)
      }
      this.renderSessionsTable()
    } catch(e) { alert('Error: ' + e.message) }
  },

  async closeSession(id) {
    const cash = prompt(I18n.t('session.end_cash', 'Closing Cash amount:'), '0')
    if (cash === null) return
    try {
      await this.api('POST', `/sessions/${id}/close`, {
        cash_register_balance_end: parseFloat(cash) || 0,
      })
      this.renderSessionsTable()
      this.renderDashboard()
    } catch(e) { alert('Error: ' + e.message) }
  },

  // === DASHBOARD ===

  async renderDashboard() {
    try {
      const res = await this.api('GET', '/dashboard')
      const d = res.data
      const cards = document.getElementById('dashboard-cards')
      const isAdmin = this.user && this.user.role === 'admin'
      cards.innerHTML = `
        <div class="dash-card"><div class="dash-icon">💰</div><div class="dash-value">${this.currencyFormat(d.today_sales || 0)}</div><div class="dash-label">${I18n.t('dashboard.today_sales', "Today's Sales")}</div></div>
        <div class="dash-card"><div class="dash-icon">📋</div><div class="dash-value">${d.today_orders || 0}</div><div class="dash-label">${I18n.t('dashboard.today_orders', 'Orders Today')}</div></div>
        <div class="dash-card"><div class="dash-icon">📦</div><div class="dash-value">${d.total_products || 0}</div><div class="dash-label">${I18n.t('dashboard.active_products', 'Active Products')}</div></div>
        ${isAdmin ? `<div class="dash-card"><div class="dash-icon">💎</div><div class="dash-value">${this.currencyFormat(d.inventory_value || 0)}</div><div class="dash-label">${I18n.t('dashboard.inventory_value', 'Inventory Value')}</div></div>` : ''}
        <div class="dash-card"><div class="dash-icon">👥</div><div class="dash-value">${d.total_customers || 0}</div><div class="dash-label">${I18n.t('dashboard.active_customers', 'Active Customers')}</div></div>
      `

      const orderRes = await this.api('GET', '/orders')
      const orders = (orderRes.data || []).slice(0, 10)
      const container = document.getElementById('dashboard-orders')
      if (!orders.length) {
        container.innerHTML = `<p style="color:var(--text-light);padding:16px">${I18n.t('order.no_orders', 'No orders')}</p>`
      } else {
        container.innerHTML = `<div style="background:var(--bg-card);border-radius:var(--radius);box-shadow:var(--shadow);overflow-x:auto">
          <table><thead><tr><th>${I18n.t('order.ref', 'Order')}</th><th>${I18n.t('order.total', 'Total')}</th><th>${I18n.t('order.status', 'Status')}</th></tr></thead><tbody>
          ${orders.map(o => `<tr><td>${o.name || o.id}</td><td>${this.currencyFormat(o.amount_total)}</td><td><span class="status-badge status-${o.state}">${o.state}</span></td></tr>`).join('')}
        </tbody></table></div>`
      }
    } catch(e) { console.error(e) }
  },

  // === REPORTS ===

  async generateReport() {
    const period = document.getElementById('report-period').value
    try {
      const res = await this.api('GET', `/reports/sales?period=${period}`)
      const r = res.data
      const container = document.getElementById('report-results')
      container.innerHTML = `
        <div class="report-summary">
          <div class="report-stat"><div class="stat-value">${this.currencyFormat(r.total_sales || 0)}</div><div class="stat-label">${I18n.t('report.total_sales', 'Total Sales')}</div></div>
          <div class="report-stat"><div class="stat-value">${r.total_orders || 0}</div><div class="stat-label">${I18n.t('report.total_orders', 'Total Orders')}</div></div>
          <div class="report-stat"><div class="stat-value">${this.currencyFormat(r.avg_order || 0)}</div><div class="stat-label">${I18n.t('report.avg_order', 'Avg Order')}</div></div>
        </div>
        <div style="max-height:400px;overflow-y:auto">
          <table><thead><tr><th>${I18n.t('order.ref', 'Order')}</th><th>${I18n.t('order.items', 'Items')}</th><th>${I18n.t('order.total', 'Total')}</th><th>${I18n.t('order.date', 'Date')}</th></tr></thead><tbody>
          ${(r.orders || []).map(o => {
            const items = (o.lines || []).map(l => `${l.product_name || 'Product'} x${l.qty}`).join(', ') || '-'
            return `<tr><td>${o.name || o.id}</td><td style="max-width:250px;white-space:normal">${items}</td><td>${this.currencyFormat(o.amount_total)}</td><td>${(o.date_order || '').substring(0, 10)}</td></tr>`
          }).join('')}
        </tbody></table></div>`
    } catch(e) { alert('Error: ' + e.message) }
  },

  exportProductsCsv() {
    const rows = [['Name','Price','Cost','Quantity','Category','Barcode','Expiration Date']]
    this.products.forEach(p => {
      rows.push([
        p.name || '',
        p.list_price || 0,
        p.cost_price || 0,
        p.available_qty || 0,
        (p.categ_id && p.categ_id.name) || '',
        p.barcode || '',
        (p.expiration_date || '').substring(0, 10),
      ])
    })
    const csv = rows.map(r => r.map(v => {
      const s = String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n') ? '"' + s.replace(/"/g, '""') + '"' : s
    }).join(',')).join('\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `inventory_${new Date().toISOString().slice(0,10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },

  async exportReportCsv() {
    const period = document.getElementById('report-period').value
    try {
      const res = await fetch(`/api/reports/sales/export?period=${period}`, { credentials: 'same-origin' })
      if (!res.ok) throw new Error('Export failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sales_report_${period}_${new Date().toISOString().slice(0,10)}.csv`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch(e) {
      alert('Export error: ' + e.message)
    }
  },

  // === SETTINGS ===

  renderSettings() {
    document.getElementById('settings-lang').value = I18n.currentLang
    this.ensureDefaultCurrency()
    const curSelect = document.getElementById('settings-currency')
    curSelect.innerHTML = (this.currencies || []).map(c =>
      `<option value="${c.id}" ${this.currency && this.currency.id === c.id ? 'selected' : ''}>${c.name} (${c.symbol})</option>`
    ).join('')
    if (this.company) {
      document.getElementById('settings-company').value = this.company.name || ''
      this.displayLogo(this.company.logo)
    }
    document.getElementById('settings-low-stock').value = this.lowStockThreshold || 5
    this.renderDeliveryZonesSettings()
  },

  async renderDeliveryZonesSettings() {
    try {
      const res = await this.api('GET', '/delivery-zones')
      this.deliveryZones = res.data || []
    } catch(e) { this.deliveryZones = this.deliveryZones || [] }
    const container = document.getElementById('settings-delivery-zones')
    const zones = this.deliveryZones || []
    if (!zones.length) {
      container.innerHTML = `<p style="font-size:13px;color:var(--text-light)">${I18n.t('delivery.no_zones', 'No zones configured')}</p>`
      return
    }
    container.innerHTML = `<table style="font-size:13px"><thead><tr><th>${I18n.t('delivery.zone', 'Zone')}</th><th>${I18n.t('delivery.cost', 'Cost')}</th><th></th></tr></thead><tbody>
      ${zones.map(z => `<tr>
        <td>${this._esc(z.name)}</td>
        <td>${this.currencyFormat(z.cost)}</td>
        <td><button class="btn btn-sm btn-primary edit-dz" data-id="${z.id}">${I18n.t('common.edit', 'Edit')}</button>
            <button class="btn btn-sm btn-danger delete-dz" data-id="${z.id}">${I18n.t('common.delete', 'Delete')}</button></td>
      </tr>`).join('')}
    </tbody></table>`
    container.querySelectorAll('.edit-dz').forEach(btn => {
      btn.onclick = () => this.showDeliveryZoneModal(parseInt(btn.dataset.id))
    })
    container.querySelectorAll('.delete-dz').forEach(btn => {
      btn.onclick = () => this.deleteDeliveryZone(parseInt(btn.dataset.id))
    })
  },

  showDeliveryZoneModal(id) {
    const zone = id ? (this.deliveryZones || []).find(z => z.id === id) : null
    const title = zone ? I18n.t('delivery.edit_zone', 'Edit Zone') : I18n.t('delivery.add_zone', 'Add Zone')
    let html = `<h3>${title}</h3>
      <div class="form-group"><label data-i18n="delivery.zone">Zone Name</label><input id="dz-name" value="${zone ? this._esc(zone.name || '') : ''}"></div>
      <div class="form-group"><label data-i18n="delivery.cost">Delivery Cost</label><input type="number" id="dz-cost" step="100" value="${zone ? zone.cost || 0 : 0}"></div>
      <div class="btn-group">
        <button class="btn btn-primary" id="dz-save">${I18n.t('common.save', 'Save')}</button>
        <button class="btn btn-secondary" id="dz-cancel">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)
    document.getElementById('dz-save').onclick = async () => {
      const name = document.getElementById('dz-name').value.trim()
      const cost = parseFloat(document.getElementById('dz-cost').value) || 0
      if (!name) { alert('Name required'); return }
      try {
        if (zone) {
          await this.api('PUT', `/delivery-zones/${zone.id}`, { name, cost })
        } else {
          await this.api('POST', '/delivery-zones', { name, cost })
        }
        this.closeModal()
        this.renderDeliveryZonesSettings()
      } catch(e) { alert('Error: ' + e.message) }
    }
    document.getElementById('dz-cancel').onclick = () => this.closeModal()
  },

  async deleteDeliveryZone(id) {
    if (!confirm(I18n.t('common.confirm', 'Confirm') + '?')) return
    await this.api('DELETE', `/delivery-zones/${id}`)
    this.deliveryZones = (this.deliveryZones || []).filter(z => z.id !== id)
    this.renderDeliveryZonesSettings()
  },

  displayLogo(base64) {
    const loginLogo = document.getElementById('login-logo')
    const navLogo = document.getElementById('nav-logo-img')
    const navBrandText = document.getElementById('nav-brand-text')
    const preview = document.getElementById('settings-logo-preview')
    const prompt = document.getElementById('settings-logo-prompt')
    const area = document.getElementById('settings-logo-area')
    if (base64) {
      const src = `data:image/png;base64,${base64}`
      loginLogo.innerHTML = `<img src="${src}" style="max-width:180px;max-height:80px">`
      navLogo.src = src; navLogo.style.display = ''
      navBrandText.style.display = 'none'
      if (preview) {
        preview.src = src; preview.style.display = 'block'
        prompt.textContent = I18n.t('settings.change_logo', 'Change Logo')
        if (area) area.classList.add('has-image')
      }
    } else {
      loginLogo.innerHTML = '🛒'
      navLogo.style.display = 'none'
      navBrandText.style.display = ''
      if (preview) { preview.style.display = 'none'; prompt.textContent = I18n.t('settings.upload_logo', 'Upload Logo') }
    }
  },

  async saveSettings() {
    const lang = document.getElementById('settings-lang').value
    const companyName = document.getElementById('settings-company').value
    const companyData = {}
    if (companyName) companyData.name = companyName
    if (this._newLogoBase64 !== null) companyData.logo = this._newLogoBase64
    if (Object.keys(companyData).length) {
      await this.api('PUT', '/company', companyData)
    }
    this._newLogoBase64 = null

    const threshold = parseInt(document.getElementById('settings-low-stock').value) || 5
    await this.api('PUT', '/config', { low_stock_threshold: threshold })
    this.lowStockThreshold = threshold

    const compRes = await this.api('GET', '/company')
    this.company = compRes.data
    this.displayLogo(this.company ? this.company.logo : null)

    I18n.setLang(lang)
    this.currency = (this.currencies || []).find(c => c.id === parseInt(document.getElementById('settings-currency').value)) || this.currency
    document.getElementById('settings-message').textContent = I18n.t('settings.saved', 'Settings saved!')
    setTimeout(() => document.getElementById('settings-message').textContent = '', 3000)
    this.renderAll()
  },

  // === USERS ===

  async renderUsersTable() {
    if (!this.hasScreen('users')) return
    try {
      const res = await this.api('GET', '/users')
      this.users = res.data || []
    } catch(e) {
      this.users = []
      return
    }
    const tbody = document.getElementById('users-tbody')
    if (!this.users.length) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-light)">${I18n.t('user.no_users', 'No users')}</td></tr>`
      return
    }
    const canEdit = this.hasAction('user.write')
    const canDelete = this.hasAction('user.delete')
    const selfId = this.user ? this.user.id : null
    tbody.innerHTML = this.users.map(u => `
      <tr>
        <td>${u.login || ''}</td>
        <td>${u.name || ''}</td>
        <td>${u.email || '-'}</td>
        <td><span class="status-badge">${u.role || ''}</span></td>
        <td>${u.active !== false ? `<span class="status-badge status-done">Active</span>` : `<span class="status-badge status-cancelled">Inactive</span>`}</td>
        <td>${canEdit ? `<button class="btn btn-sm btn-primary edit-user" data-id="${u.id}">${I18n.t('common.edit', 'Edit')}</button>` : '-'}</td>
        <td>${canDelete && u.id !== selfId ? `<button class="btn btn-sm btn-danger delete-user" data-id="${u.id}">${I18n.t('common.delete', 'Delete')}</button>` : '-'}</td>
      </tr>
    `).join('')
    tbody.querySelectorAll('.edit-user').forEach(btn => {
      btn.onclick = () => this.showUserModal(parseInt(btn.dataset.id))
    })
    tbody.querySelectorAll('.delete-user').forEach(btn => {
      btn.onclick = () => this.deleteUser(parseInt(btn.dataset.id))
    })
  },

  showUserModal(id) {
    const user = id ? this.users.find(u => u.id === id) : null
    const title = user ? I18n.t('user.edit', 'Edit User') : I18n.t('user.add', 'Add User')
    let html = `<h3>${title}</h3>
      <div class="form-group"><label data-i18n="login.username">Login</label><input id="u-login" value="${user ? this._esc(user.login || '') : ''}" ${user ? 'readonly' : ''}></div>
      <div class="form-group"><label data-i18n="user.full_name">Full Name</label><input id="u-name" value="${user ? this._esc(user.name || '') : ''}"></div>
      <div class="form-group"><label data-i18n="user.email">Email</label><input id="u-email" value="${user ? this._esc(user.email || '') : ''}"></div>
      <div class="form-group"><label data-i18n="user.password">Password</label><input type="password" id="u-password" value="" ${user ? `placeholder="Leave empty to keep current"` : ''}></div>
      <div class="form-group"><label data-i18n="user.role">Role</label><select id="u-role">
        <option value="admin" ${user && user.role === 'admin' ? 'selected' : ''}>Administrator</option>
        <option value="manager" ${user && user.role === 'manager' ? 'selected' : ''}>Manager</option>
        <option value="cashier" ${user && user.role === 'cashier' ? 'selected' : ''}>Cashier</option>
      </select></div>
      <div class="form-group">
        <label><input type="checkbox" id="u-active" ${user && user.active !== false ? 'checked' : ''}> Active</label>
      </div>
      <div class="btn-group">
        <button class="btn btn-primary" id="u-save">${I18n.t('common.save', 'Save')}</button>
        <button class="btn btn-secondary" id="u-cancel">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)
    document.getElementById('u-save').onclick = async () => {
      const data = {
        name: document.getElementById('u-name').value,
        email: document.getElementById('u-email').value,
        role: document.getElementById('u-role').value,
        active: document.getElementById('u-active').checked,
      }
      const pwd = document.getElementById('u-password').value
      if (pwd) data.password = pwd
      try {
        if (user) {
          await this.api('PUT', `/users/${user.id}`, data)
        } else {
          data.login = document.getElementById('u-login').value
          if (!data.login || !pwd) { alert('Login and password required'); return }
          await this.api('POST', '/users', data)
        }
        this.closeModal()
        this.renderUsersTable()
      } catch(e) { alert('Error: ' + e.message) }
    }
    document.getElementById('u-cancel').onclick = () => this.closeModal()
  },

  async deleteUser(id) {
    if (!confirm(I18n.t('common.confirm', 'Confirm') + '?')) return
    await this.api('DELETE', `/users/${id}`)
    this.users = this.users.filter(u => u.id !== id)
    this.renderUsersTable()
  },

  // === CATEGORIES ===

  showCategoryListModal() {
    const cats = this.productCategories || []
    const canEdit = this.hasAction('product.write')
    const canDelete = this.hasAction('product.delete')
    let html = `<h3>${I18n.t('category.manage', 'Manage Categories')}</h3>
      <button class="btn btn-sm btn-primary" id="cat-list-add" style="margin-bottom:12px">${I18n.t('category.add', 'Add Category')}</button>
      <div style="max-height:300px;overflow-y:auto">`
    if (!cats.length) {
      html += `<p style="color:var(--text-light)">${I18n.t('category.no_categories', 'No categories')}</p>`
    } else {
      html += `<table><thead><tr><th>${I18n.t('category.name', 'Name')}</th><th>${I18n.t('common.edit', 'Edit')}</th><th>${I18n.t('common.delete', 'Delete')}</th></tr></thead><tbody>`
      cats.forEach(c => {
        html += `<tr><td>${this._esc(c.name)}</td>
          <td>${canEdit ? `<button class="btn btn-sm btn-primary edit-cat" data-id="${c.id}">${I18n.t('common.edit', 'Edit')}</button>` : '-'}</td>
          <td>${canDelete ? `<button class="btn btn-sm btn-danger delete-cat" data-id="${c.id}">${I18n.t('common.delete', 'Delete')}</button>` : '-'}</td>
        </tr>`
      })
      html += `</tbody></table>`
    }
    html += `</div>
      <div class="btn-group"><button class="btn btn-secondary" id="cat-list-close">${I18n.t('common.close', 'Close')}</button></div>`
    this.showModal(html)
    document.getElementById('cat-list-add').onclick = () => { this.closeModal(); this.showCategoryModal() }
    document.getElementById('cat-list-close').onclick = () => this.closeModal()
    document.querySelectorAll('.edit-cat').forEach(btn => {
      btn.onclick = () => { this.closeModal(); this.showCategoryModal(parseInt(btn.dataset.id)) }
    })
    document.querySelectorAll('.delete-cat').forEach(btn => {
      btn.onclick = () => { this.closeModal(); this.deleteCategory(parseInt(btn.dataset.id)) }
    })
  },

  showCategoryModal(id) {
    const cat = id ? (this.productCategories || []).find(c => c.id === id) : null
    const title = cat ? I18n.t('category.edit', 'Edit Category') : I18n.t('category.add', 'Add Category')
    let html = `<h3>${title}</h3>
      <div class="form-group"><label data-i18n="category.name">Name</label><input id="cat-name" value="${cat ? this._esc(cat.name || '') : ''}"></div>
      <div class="form-group"><label data-i18n="category.description">Description</label><textarea id="cat-desc" rows="3">${cat ? this._esc(cat.description || '') : ''}</textarea></div>
      <div class="btn-group">
        <button class="btn btn-primary" id="cat-save">${I18n.t('common.save', 'Save')}</button>
        <button class="btn btn-secondary" id="cat-cancel">${I18n.t('common.cancel', 'Cancel')}</button>
      </div>`
    this.showModal(html)
    document.getElementById('cat-save').onclick = async () => {
      const name = document.getElementById('cat-name').value.trim()
      if (!name) { alert('Name required'); return }
      const data = { name, description: document.getElementById('cat-desc').value }
      try {
        if (cat) {
          await this.api('PUT', `/product-categories/${cat.id}`, data)
        } else {
          await this.api('POST', '/product-categories', data)
        }
        this.closeModal()
        const res = await this.api('GET', '/product-categories')
        this.productCategories = res.data || []
        this.renderAll()
      } catch(e) { alert('Error: ' + e.message) }
    }
    document.getElementById('cat-cancel').onclick = () => this.closeModal()
  },

  async deleteCategory(id) {
    if (!confirm(I18n.t('common.confirm', 'Confirm') + '?')) return
    await this.api('DELETE', `/product-categories/${id}`)
    this.productCategories = this.productCategories.filter(c => c.id !== id)
    this.renderAll()
  },

  // === MODAL ===

  showModal(html) {
    document.getElementById('modal-content').innerHTML = html
    document.getElementById('modal-overlay').style.display = 'flex'
  },

  closeModal() {
    document.getElementById('modal-overlay').style.display = 'none'
  }
}

document.addEventListener('DOMContentLoaded', () => App.init())
