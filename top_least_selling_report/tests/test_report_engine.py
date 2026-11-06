# -*- coding: utf-8 -*-
"""Unit tests of the pure computation core (no database data needed)."""
from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.top_least_selling_report.utils import report_engine as engine


def _row(product_id, name, qty, sales, margin, group_id=False, group_name=False, zero_fill=False):
    return {
        'group_id': group_id, 'group_name': group_name, 'product_id': product_id,
        'product_name': name, 'uom_id': 1, 'qty': qty, 'sales': sales, 'margin': margin,
        'zero_fill': zero_fill,
    }


@tagged('post_install', '-at_install', 'top_least_selling_report')
class TestReportEngine(TransactionCase):

    # ---- elementary math -------------------------------------------------
    def test_financials_and_margin(self):
        fin = engine.compute_financials(15, 220.0, 130.0)
        self.assertAlmostEqual(fin['cost'], 90.0)
        self.assertAlmostEqual(fin['profit'], 130.0)
        self.assertAlmostEqual(fin['margin_pct'], 130.0 / 220.0 * 100.0)
        zero = engine.compute_financials(0, 0.0, 0.0)
        self.assertEqual(zero['margin_pct'], 0.0, "No division by zero when nothing was sold")
        loss = engine.compute_financials(1, 100.0, -25.0)
        self.assertAlmostEqual(loss['cost'], 125.0)
        self.assertAlmostEqual(loss['margin_pct'], -25.0)

    def test_pct_change(self):
        self.assertAlmostEqual(engine.pct_change(15, 20), -25.0)
        self.assertAlmostEqual(engine.pct_change(48, 24), 100.0)
        self.assertAlmostEqual(engine.pct_change(-5, -10), 50.0, "Improvement of a negative profit is positive")
        self.assertEqual(engine.pct_change(10, 0), 0.0)

    # ---- periods ---------------------------------------------------------
    def test_previous_period(self):
        self.assertEqual(engine.previous_period(date(2026, 3, 1), date(2026, 3, 31)),
                         (date(2026, 1, 29), date(2026, 2, 28)))
        self.assertEqual(engine.previous_period(date(2026, 3, 10), date(2026, 3, 10)),
                         (date(2026, 3, 9), date(2026, 3, 9)))
        prev_from, prev_to = engine.previous_period(date(2026, 1, 1), date(2026, 3, 31))
        self.assertEqual((prev_to - prev_from).days, (date(2026, 3, 31) - date(2026, 1, 1)).days)
        self.assertEqual(prev_to, date(2025, 12, 31))

    def test_previous_year(self):
        self.assertEqual(engine.previous_year(date(2026, 3, 1), date(2026, 3, 31)),
                         (date(2025, 3, 1), date(2025, 3, 31)))
        self.assertEqual(engine.previous_year(date(2024, 2, 1), date(2024, 2, 29)),
                         (date(2023, 2, 1), date(2023, 2, 28)), "Leap day maps to 28 February")

    # ---- ranking ---------------------------------------------------------
    def _current(self):
        return [
            _row(1, 'Alpha', 15, 220.0, 130.0),
            _row(2, 'Bravo', 2, 200.0, 140.0),
            _row(3, 'Charlie', 24, 48.0, 24.0),
        ]

    def test_ranking_by_each_metric(self):
        expectations = {
            'quantity': ([3, 1], [2, 1]),
            'revenue': ([1, 2], [3, 2]),
            'profit': ([2, 1], [3, 1]),
        }
        for metric, (top_ids, least_ids) in expectations.items():
            result = engine.build_report(self._current(), metric=metric, limit=2)
            top = [l['product_id'] for l in result['lines'] if l['section'] == 'top']
            least = [l['product_id'] for l in result['lines'] if l['section'] == 'least']
            self.assertEqual(top, top_ids, metric)
            self.assertEqual(least, least_ids, metric)
            ranks = [l['rank'] for l in result['lines'] if l['section'] == 'top']
            self.assertEqual(ranks, [1, 2])

    def test_tie_break_is_deterministic(self):
        rows = [_row(9, 'Zulu', 5, 10, 1), _row(4, 'alpha', 5, 10, 1), _row(7, 'Mike', 5, 10, 1)]
        result = engine.build_report(rows, metric='quantity', limit=3)
        top = [l['product_id'] for l in result['lines'] if l['section'] == 'top']
        self.assertEqual(top, [4, 7, 9], "Equal values are ordered by product name")

    def test_comparison(self):
        previous = [_row(1, 'Alpha', 20, 300.0, 180.0), _row(3, 'Charlie', 12, 24.0, 12.0)]
        result = engine.build_report(self._current(), previous, metric='quantity', limit=3)
        top = {l['product_id']: l for l in result['lines'] if l['section'] == 'top'}
        alpha, bravo, charlie = top[1], top[2], top[3]
        self.assertAlmostEqual(alpha['prev_qty'], 20)
        self.assertAlmostEqual(alpha['qty_change'], -25.0)
        self.assertAlmostEqual(alpha['sales_change'], (220.0 - 300.0) / 300.0 * 100)
        self.assertAlmostEqual(alpha['profit_change'], (130.0 - 180.0) / 180.0 * 100)
        self.assertEqual(alpha['prev_rank'], 1)
        self.assertEqual(charlie['prev_rank'], 2)
        self.assertAlmostEqual(charlie['qty_change'], 100.0)
        self.assertTrue(bravo['is_new'])
        self.assertEqual(bravo['prev_rank'], 0)
        summary = result['summary']
        self.assertAlmostEqual(summary['sales'], 468.0)
        self.assertAlmostEqual(summary['prev_sales'], 324.0)
        self.assertAlmostEqual(summary['sales_change'], (468.0 - 324.0) / 324.0 * 100)

    def test_without_comparison_nothing_is_new(self):
        result = engine.build_report(self._current(), None, metric='quantity', limit=3)
        self.assertFalse(any(l['is_new'] for l in result['lines']))

    def test_groups_restart_ranking(self):
        rows = [
            _row(1, 'Alpha', 10, 150.0, 90.0, 11, 'North'),
            _row(2, 'Bravo', 2, 200.0, 140.0, 11, 'North'),
            _row(1, 'Alpha', 5, 70.0, 40.0, 12, 'South'),
            _row(3, 'Charlie', 24, 48.0, 24.0, 12, 'South'),
        ]
        result = engine.build_report(rows, metric='quantity', limit=5)
        top = [(l['group_name'], l['product_id'], l['rank'], l['group_sequence'])
               for l in result['lines'] if l['section'] == 'top']
        self.assertEqual(top, [('North', 1, 1, 1), ('North', 2, 2, 1), ('South', 3, 1, 2), ('South', 1, 2, 2)])

    def test_zero_fill_rows(self):
        rows = self._current() + [_row(4, 'Delta', 0, 0, 0, zero_fill=True)]
        result = engine.build_report(rows, metric='quantity', limit=2)
        least = [l['product_id'] for l in result['lines'] if l['section'] == 'least']
        self.assertEqual(least, [4, 2])
        self.assertEqual(result['summary']['product_count'], 3, "Zero-sale products are not counted as sold")

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            engine.build_report(self._current(), metric='volume')
        with self.assertRaises(ValueError):
            engine.build_report(self._current(), limit=0)
