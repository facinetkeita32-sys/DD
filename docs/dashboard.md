# Tableau de bord — enhancement and recovery

## Architecture reviewed before implementation

- Backend: Flask blueprints, Gunicorn, custom Odoo-like ORM and process-local
  cache; SQLite or PostgreSQL through `pos_system/db.py`.
- Frontend: existing HTML/CSS and vanilla JavaScript (`App`), with JSON dictionaries
  and `I18n`. No frontend framework, chart library, or new runtime dependency.
- Existing reporting: `/api/dashboard`, `/api/reports/sales`, and `/api/orders`.
  These APIs retain their existing contracts and implementations.
- Existing schema: orders reference users, sessions, customers, and optionally
  companies. Lines store quantity and discounted subtotal. Configurations carry
  currency, precision, and the low-stock threshold. There is no store-membership
  relationship on users, and product/customer records are shared within the
  installation. Purchasing is not present on this branch.
- Authentication: existing Flask sessions, login decorator, restored-session
  generation, and admin/manager/cashier roles. No changes to authentication,
  role definitions, or action permissions are needed for this enhancement.

## Additive reporting API

`GET /api/dashboard/analytics?period=30d` uses the existing authenticated user's
role and dashboard screen entitlement. `period` accepts `today`, `7d`, `30d`,
`90d`, or `custom` with inclusive `date_from` and `date_to` ISO dates. Custom
periods are capped at 366 days. Unknown filters are rejected; there is no
client-controlled user/company/store scope. Responses are marked `no-store`.

- Admins and managers see the existing single-business reporting scope.
- Cashiers see only their own orders, previous-period values, product rankings,
  and recent transactions. Customer identities/contact details are never returned.
- Stock summaries are only provided to admin/manager roles. The inventory-value
  figure remains admin-only, matching the previous dashboard UI.
- Multiple companies or conflicting configured currencies fail closed with HTTP
  409. Adding real multi-store reporting requires an explicit authorized user/store
  relationship; this UI does not invent or expose a store selector.
- Orders assigned to a different company are excluded; unassigned legacy orders
  are included only in an unambiguous single-company installation.

All projections are read-only ORM queries coordinated by the existing request
database lock. No model/table/column migrations, financial writes, checkout,
inventory, customer, purchasing, or payment workflow changes are made.

## Indicator definitions

- Revenue: sum of stored `amount_total` for `paid`/`done` orders, consistent with
  the existing sales report. Includes stored tax/delivery; no amounts recalculated.
- Orders: count of those orders; average basket: revenue divided by that count.
- Outstanding: positive stored total minus stored paid amount for `pending`
  orders created within the selected period, not the full historic receivables.
- Comparisons use the immediately preceding interval of equal length. A zero
  reference is shown as unavailable rather than an invented percentage.
- Trend includes zero-sale days. Long ranges group adjacent days into at most
  30 chart points; the accessible data table retains all daily figures.
- Top products use stored discounted `price_subtotal`, excluding delivery, for
  eligible paid orders only. Deleted/archived products retain line names if present.
- Recent orders show at most 50 rows, excluding drafts. Customer fields and order
  detail links are deliberately absent from this reporting projection.
- Stock is a current snapshot independent of the selected sales period. Service
  products are excluded from low/out-of-stock counts. Inventory valuation uses
  the prior dashboard convention: positive cost, otherwise selling price.
- Dates follow the server's existing local clock; timezone behavior is unchanged.
- Localized French/English number grouping is presentation-only. The configured currency symbol,
  symbol position, and decimal places are retained, defaulting to FG/GNF and zero
  decimal places when unconfigured. No currency conversion is performed.

## UI and localization

The reusable `Dashboard` module and scoped `dashboard.css` reuse the application's
buttons, typography, navigation, and color tokens. Filters, refresh, keyboard-
accessible chart points/data table, loading skeletons, empty/error states, and
stale-response guards are included. BI keys use the existing dictionaries; they
provide French and English labels selected through the existing language selector.
Dates, number grouping, chart details, error messages, and accessible labels follow
the selected language. Language changes wait for their dictionary before refreshing
dynamic indicators, and late translation responses cannot overwrite a newer choice.
Light mode follows the current application. Reduced-motion preferences are honored.
Reporting loads only when the dashboard is visible, not during checkout updates.

## Recovery point

Pre-enhancement recovery point: Git commit `dc894a5` (responsive sidebar).
No database migration or business-data rewrite is necessary. Keep the normal
database backup before deploying; rolling back this enhancement requires only
restoring that code version and restarting the existing service. Do not restore
an old business database just to undo dashboard presentation changes.

## Verification

`python -m unittest discover -s tests -v` runs the existing regressions plus a
fresh-process dashboard suite against a temporary SQLite database. It checks
read-only behavior, stored totals, paid/pending/cancelled states, period boundaries,
cashier isolation, admin-only valuation, authentication, scope tampering, currency
precision, and ambiguous-company rejection. Browser checks cover responsive layouts,
filters, chart keyboard interaction, loading/empty/error/retry states, escaping,
and out-of-order asynchronous responses.
