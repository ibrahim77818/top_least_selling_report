# -*- coding: utf-8 -*-
"""Pure-Python computation core of the Top & Least Selling report.

Nothing in this file imports Odoo: the wizard fetches pre-aggregated rows from
PostgreSQL (``sale.report`` read_group) and hands plain dictionaries to
:func:`build_report`. Keeping the math here makes it deterministic and unit
testable in isolation.

Input row format (one row per product, or per group + product)::

    {
        'group_id': int | False,      # sales team / salesperson id, False if no grouping
        'group_name': str | False,
        'product_id': int,
        'product_name': str,
        'uom_id': int,
        'qty': float,                 # quantity in the product's reference UoM
        'sales': float,               # untaxed sale amount (company currency)
        'margin': float,              # sale amount - cost (company currency)
        'zero_fill': bool,            # optional, True for saleable products with no sales
    }
"""
from collections import OrderedDict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

METRIC_FIELDS = {
    'quantity': 'qty',
    'revenue': 'sales',
    'profit': 'profit',
}


# ---------------------------------------------------------------------------
# Elementary math
# ---------------------------------------------------------------------------
def safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def margin_percent(profit, sales):
    """Profit as a percentage of the sale amount (0 when nothing was sold)."""
    return safe_div(profit, sales) * 100.0


def pct_change(current, previous):
    """Relative change from ``previous`` to ``current`` in percent.

    Returns 0.0 when there is no previous value: the line is then flagged
    ``is_new`` instead of showing an infinite growth.
    """
    if not previous:
        return 0.0
    return (current - previous) / abs(previous) * 100.0


def compute_financials(qty, sales, margin):
    """Derive cost, profit and margin % from the aggregated sale figures."""
    qty = qty or 0.0
    sales = sales or 0.0
    margin = margin or 0.0
    return {
        'qty': qty,
        'sales': sales,
        'cost': sales - margin,
        'profit': margin,
        'margin_pct': margin_percent(margin, sales),
    }


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def previous_period(date_from, date_to):
    """Period of identical length ending the day before ``date_from``."""
    span = (date_to - date_from).days
    prev_to = date_from - timedelta(days=1)
    return prev_to - timedelta(days=span), prev_to


def previous_year(date_from, date_to):
    """Same calendar period one year earlier (29 Feb maps to 28 Feb)."""
    return date_from - relativedelta(years=1), date_to - relativedelta(years=1)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def enrich(row):
    out = dict(row)
    out.update(compute_financials(row.get('qty'), row.get('sales'), row.get('margin')))
    return out


def rank_rows(rows, metric, descending=True):
    """Sort rows on the metric; ties are broken by product name then id."""
    key = METRIC_FIELDS[metric]
    base = sorted(rows, key=lambda r: ((r.get('product_name') or '').lower(), r.get('product_id') or 0))
    # Python's sort is stable, also with reverse=True, so the tie-break order is kept.
    return sorted(base, key=lambda r: r[key], reverse=descending)


def group_rows(rows):
    groups = OrderedDict()
    for row in rows:
        groups.setdefault(row.get('group_id') or False, []).append(row)
    return groups


def _totals(rows):
    cost = sum(r['cost'] for r in rows)
    sales = sum(r['sales'] for r in rows)
    profit = sum(r['profit'] for r in rows)
    return cost, sales, profit


def build_report(current_rows, previous_rows=None, metric='quantity', limit=10):
    """Build the top and least selling sets.

    :param current_rows: rows of the reporting period
    :param previous_rows: rows of the comparison period, or None (no comparison)
    :param metric: 'quantity', 'revenue' or 'profit'
    :param limit: number of products kept in each set (per group)
    :return: {'lines': [...], 'summary': {...}}
    """
    if metric not in METRIC_FIELDS:
        raise ValueError("Unknown ranking metric: %s" % metric)
    if not limit or limit < 1:
        raise ValueError("The limit must be a positive integer.")

    compare = previous_rows is not None
    current = [enrich(r) for r in current_rows]
    previous = [enrich(r) for r in (previous_rows or [])]

    # Index the comparison period: values and overall rank inside each group.
    prev_index, prev_rank = {}, {}
    for group_id, rows in group_rows(previous).items():
        for position, row in enumerate(rank_rows(rows, metric, True), start=1):
            prev_index[(group_id, row['product_id'])] = row
            prev_rank[(group_id, row['product_id'])] = position

    # Groups ordered by total sale amount (largest first), then by name.
    groups = sorted(
        group_rows(current).items(),
        key=lambda item: (-sum(r['sales'] for r in item[1]), str(item[1][0].get('group_name') or '')),
    )

    lines = []
    for sequence, (group_id, rows) in enumerate(groups, start=1):
        for section, descending in (('top', True), ('least', False)):
            for rank, row in enumerate(rank_rows(rows, metric, descending)[:limit], start=1):
                line = {
                    'section': section,
                    'rank': rank,
                    'group_id': group_id,
                    'group_name': row.get('group_name') or False,
                    'group_sequence': sequence,
                    'product_id': row['product_id'],
                    'uom_id': row.get('uom_id'),
                    'qty': row['qty'],
                    'cost': row['cost'],
                    'sales': row['sales'],
                    'profit': row['profit'],
                    'margin_pct': row['margin_pct'],
                    'prev_qty': 0.0,
                    'prev_cost': 0.0,
                    'prev_sales': 0.0,
                    'prev_profit': 0.0,
                    'qty_change': 0.0,
                    'sales_change': 0.0,
                    'profit_change': 0.0,
                    'prev_rank': 0,
                    'is_new': False,
                }
                if compare:
                    key = (group_id, row['product_id'])
                    prev = prev_index.get(key)
                    if prev:
                        line.update({
                            'prev_qty': prev['qty'],
                            'prev_cost': prev['cost'],
                            'prev_sales': prev['sales'],
                            'prev_profit': prev['profit'],
                            'qty_change': pct_change(row['qty'], prev['qty']),
                            'sales_change': pct_change(row['sales'], prev['sales']),
                            'profit_change': pct_change(row['profit'], prev['profit']),
                            'prev_rank': prev_rank[key],
                        })
                    else:
                        line['is_new'] = bool(row['qty'] or row['sales'])
                lines.append(line)

    sold = [r for r in current if not r.get('zero_fill')]
    cost, sales, profit = _totals(sold)
    summary = {
        'product_count': len({r['product_id'] for r in sold}),
        'cost': cost,
        'sales': sales,
        'profit': profit,
        'margin_pct': margin_percent(profit, sales),
        'prev_cost': 0.0,
        'prev_sales': 0.0,
        'prev_profit': 0.0,
        'prev_margin_pct': 0.0,
        'sales_change': 0.0,
        'profit_change': 0.0,
    }
    if compare:
        p_cost, p_sales, p_profit = _totals(previous)
        summary.update({
            'prev_cost': p_cost,
            'prev_sales': p_sales,
            'prev_profit': p_profit,
            'prev_margin_pct': margin_percent(p_profit, p_sales),
            'sales_change': pct_change(sales, p_sales),
            'profit_change': pct_change(profit, p_profit),
        })
    return {'lines': lines, 'summary': summary}
