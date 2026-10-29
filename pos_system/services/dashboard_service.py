"""Read-only dashboard projections over the existing ORM and stored amounts."""
from datetime import date, datetime, timedelta

from ..models.pos_config import PosConfig
from ..models.pos_order import PosOrder
from ..models.pos_order_line import PosOrderLine
from ..models.product_product import ProductProduct
from ..models.res_company import ResCompany
from ..models.res_currency import ResCurrency


class DashboardScopeError(ValueError):
    pass


def _day(value):
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def _period(args, today):
    period = args.get('period', '30d')
    if period == 'custom':
        try:
            start = date.fromisoformat(args.get('date_from', ''))
            end = date.fromisoformat(args.get('date_to', ''))
        except (ValueError, TypeError):
            raise ValueError('Veuillez renseigner deux dates valides.')
    elif period in ('today', '7d', '30d', '90d'):
        end = today
        days = 1 if period == 'today' else int(period[:-1])
        start = end - timedelta(days=days - 1)
    else:
        raise ValueError('Période non prise en charge.')
    if (start > end or end > today or (end - start).days >= 366
            or start.toordinal() <= (end - start).days + 1):
        raise ValueError('Choisissez une période passée ou actuelle de 366 jours maximum.')
    return period, start, end


def _number(row, key):
    return row.get(key, 0) or 0


def _summary(rows):
    sales = [row for row in rows if row.get('state') in ('paid', 'done')]
    revenue = sum(_number(row, 'amount_total') for row in sales)
    return {
        'revenue': revenue,
        'orders': len(sales),
        'average_order': revenue / len(sales) if sales else 0,
        'outstanding': sum(max(0, _number(row, 'amount_total') - _number(row, 'amount_paid'))
                           for row in rows if row.get('state') == 'pending'),
    }


def get_dashboard_analytics(args, user_id, role, today=None):
    today = today or date.today()
    period, start, end = _period(args, today)
    days = (end - start).days + 1
    previous_start, previous_end = start - timedelta(days=days), start - timedelta(days=1)

    # There is no user/store membership in the current schema. Do not infer
    # authorization from a query parameter or aggregate ambiguous companies.
    companies = ResCompany.search([])
    configs = PosConfig.search([('active', '=', True)])
    company_ids = {company.id for company in companies}
    company_ids.update(config._data.get('company_id') for config in configs
                       if config._data.get('company_id'))
    if len(company_ids) > 1:
        raise DashboardScopeError('Le périmètre de société doit être défini avant de consulter ces indicateurs.')
    company_id = next(iter(company_ids), None)
    config = configs[0] if configs else None
    currency_ids = {config._data.get('currency_id') for config in configs
                    if config._data.get('currency_id')}
    if len(currency_ids) > 1:
        raise DashboardScopeError('Plusieurs devises sont configurées ; les ventes ne peuvent pas être additionnées.')
    currencies = ResCurrency.browse(list(currency_ids)) if currency_ids else []
    currency = currencies[0]._data if currencies else {}

    domain = [] if role in ('admin', 'manager') else [('user_id', '=', user_id)]
    current, previous = [], []
    for order in PosOrder.search(domain):
        row = dict(order._data, id=order.id)
        if row.get('company_id') and row['company_id'] != company_id:
            continue
        day = _day(row.get('date_order'))
        if day is None:
            continue
        row['day'] = day.isoformat()
        if start <= day <= end:
            current.append(row)
        elif previous_start <= day <= previous_end:
            previous.append(row)

    summary, comparison = _summary(current), _summary(previous)
    for key, value in summary.items():
        baseline = comparison[key]
        comparison[key] = {
            'value': baseline,
            'change_percent': (value - baseline) / abs(baseline) * 100 if baseline else None,
        }

    series = {(start + timedelta(days=i)).isoformat(): {
        'date': (start + timedelta(days=i)).isoformat(), 'revenue': 0, 'orders': 0,
    } for i in range(days)}
    paid_ids = set()
    for row in current:
        if row.get('state') in ('paid', 'done'):
            paid_ids.add(row['id'])
            series[row['day']]['revenue'] += _number(row, 'amount_total')
            series[row['day']]['orders'] += 1

    top = {}
    if paid_ids:
        # One pass, not a separate ORM query for every order or product.
        # This ORM implements "in" with a list scan; a set lookup here avoids
        # quadratic order/line matching on a long reporting interval.
        for line in PosOrderLine.search([]):
            row = line._data
            if row.get('order_id') not in paid_ids:
                continue
            pid = row.get('product_id') or 0
            entry = top.setdefault(pid, {'product_id': pid, 'name': row.get('product_name') or '',
                                         'quantity': 0, 'revenue': 0})
            entry['quantity'] += _number(row, 'qty')
            entry['revenue'] += _number(row, 'price_subtotal')
    for product in ProductProduct.browse(list(top)):
        top[product.id]['name'] = top[product.id]['name'] or product._data.get('name') or ''
    top_products = sorted(top.values(), key=lambda row: (-row['revenue'], row['product_id']))[:5]

    # Explicit projection: no customer identities, contact details, payment
    # references, user credentials, or product costs in general reporting.
    visible = [row for row in current if row.get('state') in
               ('paid', 'done', 'pending', 'cancelled', 'refunded')]
    visible.sort(key=lambda row: (str(row.get('date_order') or ''), row['id']), reverse=True)
    recent = [{key: row.get(key) for key in ('id', 'name', 'date_order', 'amount_total', 'state', 'day')}
              for row in visible[:50]]

    stock = None
    if role in ('admin', 'manager'):
        products = ProductProduct.search([('active', '=', True)])
        threshold = config._data.get('low_stock_threshold', 5) if config else 5
        threshold = 5 if threshold is None else threshold
        stocked = [p for p in products if p._data.get('type') != 'service']
        stock = {
            'products': len(products),
            'low': sum(0 < _number(p._data, 'available_qty') <= threshold for p in stocked),
            'out': sum(_number(p._data, 'available_qty') <= 0 for p in stocked),
            'threshold': threshold,
        }
        if role == 'admin':
            stock['inventory_value'] = sum(
                _number(p._data, 'available_qty') *
                (_number(p._data, 'cost_price') if _number(p._data, 'cost_price') > 0
                 else _number(p._data, 'list_price')) for p in products)

    return {
        'period': period, 'date_from': start.isoformat(), 'date_to': end.isoformat(),
        'previous_from': previous_start.isoformat(), 'previous_to': previous_end.isoformat(),
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'server_today': today.isoformat(),
        'scope': 'business' if role in ('admin', 'manager') else 'personal',
        'currency': {'symbol': currency.get('symbol') or 'FG',
                     'iso_code': currency.get('iso_code') or 'GNF',
                     'decimal_places': currency.get('decimal_places', 0),
                     'position': currency.get('position') or 'before'},
        'summary': summary, 'comparison': comparison, 'series': list(series.values()),
        'top_products': top_products, 'recent_orders': recent,
        'recent_limit': 50, 'matching_orders': len(visible), 'stock': stock,
    }
