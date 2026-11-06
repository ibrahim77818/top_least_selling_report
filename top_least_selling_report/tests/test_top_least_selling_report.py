# -*- coding: utf-8 -*-
import base64
import io
import zipfile
from datetime import date

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

ARABIC_TOP_TITLE = 'المنتجات الأكثر مبيعاً'
ARABIC_COST_HEADER = 'تكلفة الكمية المباعة'


@tagged('post_install', '-at_install', 'top_least_selling_report')
class TestTopLeastSellingReport(TransactionCase):
    """End-to-end tests on real sales orders.

    Data set (all amounts untaxed, company currency):

    Current period, March 2026
      SO1 team North / salesman:  Alpha 10 x 15 (cost 6)  -> 150 / 60 / 90
                                  Bravo  2 x 100 (cost 30) -> 200 / 60 / 140
      SO2 team South / manager:   Alpha  5 x 14 (cost 6)  ->  70 / 30 / 40
                                  Charlie 2 Dozens x 24 (cost 12/dozen) -> 24 Units, 48 / 24 / 24
      Excluded: a draft order, a cancelled order and an April order.
      A locked order (lock flag, state stays 'sale') is still counted.

    Previous period (29 Jan - 28 Feb 2026)
      SO3 team North:             Alpha 20 x 15 (cost 6)  -> 300 / 120 / 180
                                  Charlie 12 x 2 (cost 1) ->  24 / 12 / 12

    Delta is saleable and never sold.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.env.user.tz = 'UTC'
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.categ = cls.env['product.category'].create({'name': 'TLS Test Category'})

        def make_product(name, cost):
            return cls.env['product.product'].create({
                'name': name,
                'type': 'consu',
                'categ_id': cls.categ.id,
                'sale_ok': True,
                'list_price': 1.0,
                'standard_price': cost,
                'uom_id': cls.uom_unit.id,
                'uom_po_id': cls.uom_unit.id,
                'company_id': False,
            })

        cls.alpha = make_product('TLS Alpha', 6.0)
        cls.bravo = make_product('TLS Bravo', 30.0)
        cls.charlie = make_product('TLS Charlie', 1.0)
        cls.delta = make_product('TLS Delta', 5.0)

        cls.partner = cls.env['res.partner'].create({'name': 'TLS Customer'})
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'TLS Pricelist',
            'currency_id': cls.currency.id,
            'company_id': cls.company.id,
        })
        cls.team_north = cls.env['crm.team'].create({'name': 'TLS North', 'company_id': cls.company.id})
        cls.team_south = cls.env['crm.team'].create({'name': 'TLS South', 'company_id': cls.company.id})
        cls.salesman = cls.env['res.users'].create({
            'name': 'TLS Salesman',
            'login': 'tls_salesman',
            'email': 'tls.salesman@example.com',
            'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'groups_id': [Command.set([cls.env.ref('sales_team.group_sale_salesman_all_leads').id])],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'TLS Manager',
            'login': 'tls_manager',
            'email': 'tls.manager@example.com',
            'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'groups_id': [Command.set([cls.env.ref('sales_team.group_sale_manager').id])],
        })

        march = '2026-03-10 12:00:00'
        cls.order_north = cls._create_order(
            [(cls.alpha, 10, 15.0, 6.0, None), (cls.bravo, 2, 100.0, 30.0, None)],
            march, cls.team_north, cls.salesman)
        # Since Odoo 17 there is no 'done' state: a locked order keeps state 'sale'.
        cls.order_north.action_lock()
        cls._create_order(
            [(cls.alpha, 5, 14.0, 6.0, None), (cls.charlie, 2, 24.0, 12.0, cls.uom_dozen)],
            march, cls.team_south, cls.manager)
        # Must be ignored: draft, cancelled, outside the period.
        cls._create_order([(cls.bravo, 50, 100.0, 30.0, None)], march, cls.team_north, cls.salesman, state='draft')
        cls._create_order([(cls.alpha, 100, 15.0, 6.0, None)], march, cls.team_north, cls.salesman, state='cancel')
        cls._create_order([(cls.charlie, 1000, 2.0, 1.0, None)], '2026-04-05 12:00:00', cls.team_south, cls.manager)
        # Previous period.
        cls._create_order(
            [(cls.alpha, 20, 15.0, 6.0, None), (cls.charlie, 12, 2.0, 1.0, None)],
            '2026-02-15 12:00:00', cls.team_north, cls.salesman)

    @classmethod
    def _create_order(cls, lines, order_date, team, user, state='sale'):
        order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'pricelist_id': cls.pricelist.id,
            'team_id': team.id,
            'user_id': user.id,
            'company_id': cls.company.id,
            'order_line': [Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': (uom or product.uom_id).id,
                'price_unit': price,
                'purchase_price': cost,
                'tax_id': [Command.clear()],
            }) for product, qty, price, cost, uom in lines],
        })
        if state in ('sale', 'cancel'):
            order.action_confirm()
        if state == 'cancel':
            order._action_cancel()
        # action_confirm() stamps date_order with "now": put the wanted date back.
        order.write({'date_order': order_date, 'team_id': team.id})
        return order

    def _wizard(self, **kwargs):
        vals = {
            'date_from': date(2026, 3, 1),
            'date_to': date(2026, 3, 31),
            'categ_ids': [Command.set(self.categ.ids)],
            'company_ids': [Command.set(self.company.ids)],
            'rank_by': 'quantity',
            'limit': 10,
        }
        vals.update(kwargs)
        return self.env['top.least.selling.wizard'].create(vals)

    @staticmethod
    def _section(wizard, section, team=None):
        lines = wizard.line_ids.filtered(lambda l: l.section == section)
        if team is not None:
            lines = lines.filtered(lambda l: l.team_id == team)
        return lines.sorted('rank')

    # ------------------------------------------------------------------
    # Financial and volume metrics
    # ------------------------------------------------------------------
    def test_01_metrics_and_margin_math(self):
        wizard = self._wizard()
        wizard._generate_lines()
        top = self._section(wizard, 'top')
        self.assertEqual(top.product_id, self.charlie + self.alpha + self.bravo,
                         "Ranked by quantity: 24 Units, 15 Units, 2 Units")
        by_product = {line.product_id: line for line in top}

        alpha = by_product[self.alpha]
        self.assertAlmostEqual(alpha.qty_sold, 15.0)
        self.assertEqual(alpha.uom_id, self.uom_unit)
        self.assertAlmostEqual(alpha.sales_amount, 220.0)
        self.assertAlmostEqual(alpha.cost_amount, 90.0)
        self.assertAlmostEqual(alpha.profit_amount, 130.0)
        self.assertAlmostEqual(alpha.margin_percent, 130.0 / 220.0 * 100.0, places=2)

        bravo = by_product[self.bravo]
        self.assertAlmostEqual(bravo.qty_sold, 2.0)
        self.assertAlmostEqual(bravo.sales_amount, 200.0, msg="The draft order must be ignored")
        self.assertAlmostEqual(bravo.cost_amount, 60.0)
        self.assertAlmostEqual(bravo.profit_amount, 140.0)
        self.assertAlmostEqual(bravo.margin_percent, 70.0, places=2)

        for line in top:
            self.assertAlmostEqual(line.sales_amount - line.cost_amount, line.profit_amount, places=2)
            self.assertEqual(line.currency_id, self.currency)

        self.assertEqual(wizard.summary_product_count, 3)
        self.assertAlmostEqual(wizard.summary_sales, 468.0)
        self.assertAlmostEqual(wizard.summary_cost, 174.0)
        self.assertAlmostEqual(wizard.summary_profit, 294.0)
        self.assertAlmostEqual(wizard.summary_margin_percent, 294.0 / 468.0 * 100.0, places=2)

    def test_01b_locked_orders_are_counted(self):
        self.assertTrue(self.order_north.locked)
        self.assertEqual(self.order_north.state, 'sale')
        wizard = self._wizard()
        wizard._generate_lines()
        bravo = self._section(wizard, 'top').filtered(lambda l: l.product_id == self.bravo)
        self.assertAlmostEqual(bravo.sales_amount, 200.0, msg="Bravo is only sold on the locked order")

    def test_02_uom_conversion(self):
        """Lines sold in Dozens are reported in the product's reference unit."""
        wizard = self._wizard()
        wizard._generate_lines()
        charlie = self._section(wizard, 'top').filtered(lambda l: l.product_id == self.charlie)
        self.assertAlmostEqual(charlie.qty_sold, 24.0)
        self.assertAlmostEqual(charlie.sales_amount, 48.0)
        self.assertAlmostEqual(charlie.cost_amount, 24.0)

    def test_03_rank_by_revenue_and_profit(self):
        wizard = self._wizard(rank_by='revenue', limit=2)
        wizard._generate_lines()
        self.assertEqual(self._section(wizard, 'top').product_id, self.alpha + self.bravo)
        self.assertEqual(self._section(wizard, 'least').product_id, self.charlie + self.bravo)

        wizard = self._wizard(rank_by='profit', limit=2)
        wizard._generate_lines()
        self.assertEqual(self._section(wizard, 'top').product_id, self.bravo + self.alpha)
        self.assertEqual(self._section(wizard, 'least').product_id, self.charlie + self.alpha)

    def test_04_least_selling_with_zero_sales(self):
        wizard = self._wizard(limit=2)
        wizard._generate_lines()
        self.assertEqual(self._section(wizard, 'least').product_id, self.bravo + self.alpha)

        wizard = self._wizard(limit=2, include_zero_sales=True)
        wizard._generate_lines()
        least = self._section(wizard, 'least')
        self.assertEqual(least.product_id, self.delta + self.bravo)
        self.assertEqual(least[0].qty_sold, 0.0)
        self.assertEqual(wizard.summary_product_count, 3)

    # ------------------------------------------------------------------
    # Comparative periods
    # ------------------------------------------------------------------
    def test_05_comparison_dates(self):
        wizard = self._wizard(compare_mode='previous_period')
        self.assertEqual(wizard.compare_date_from, date(2026, 1, 29))
        self.assertEqual(wizard.compare_date_to, date(2026, 2, 28))
        wizard.compare_mode = 'previous_year'
        self.assertEqual(wizard.compare_date_from, date(2025, 3, 1))
        self.assertEqual(wizard.compare_date_to, date(2025, 3, 31))
        wizard.write({'compare_mode': 'custom', 'compare_date_from': date(2026, 2, 1),
                      'compare_date_to': date(2026, 2, 20)})
        self.assertEqual(wizard.compare_date_from, date(2026, 2, 1))
        wizard.compare_mode = 'none'
        self.assertFalse(wizard.compare_date_from)

    def test_06_comparison_figures(self):
        wizard = self._wizard(compare_mode='previous_period')
        wizard._generate_lines()
        top = {line.product_id: line for line in self._section(wizard, 'top')}

        alpha = top[self.alpha]
        self.assertAlmostEqual(alpha.prev_qty_sold, 20.0)
        self.assertAlmostEqual(alpha.prev_sales_amount, 300.0)
        self.assertAlmostEqual(alpha.prev_cost_amount, 120.0)
        self.assertAlmostEqual(alpha.prev_profit_amount, 180.0)
        self.assertAlmostEqual(alpha.qty_change_percent, -25.0, places=2)
        self.assertAlmostEqual(alpha.sales_change_percent, -26.67, places=2)
        self.assertAlmostEqual(alpha.profit_change_percent, -27.78, places=2)
        self.assertEqual(alpha.prev_rank, 1)
        self.assertFalse(alpha.is_new)

        charlie = top[self.charlie]
        self.assertAlmostEqual(charlie.qty_change_percent, 100.0, places=2)
        self.assertAlmostEqual(charlie.sales_change_percent, 100.0, places=2)
        self.assertEqual(charlie.prev_rank, 2)

        bravo = top[self.bravo]
        self.assertTrue(bravo.is_new)
        self.assertEqual(bravo.prev_rank, 0)
        self.assertEqual(bravo.sales_change_percent, 0.0)

        self.assertAlmostEqual(wizard.summary_prev_sales, 324.0)
        self.assertAlmostEqual(wizard.summary_prev_profit, 192.0)
        self.assertAlmostEqual(wizard.summary_sales_change, (468.0 - 324.0) / 324.0 * 100.0, places=2)
        self.assertAlmostEqual(wizard.summary_profit_change, (294.0 - 192.0) / 192.0 * 100.0, places=2)

    def test_07_comparison_with_empty_period(self):
        wizard = self._wizard(compare_mode='previous_year')
        wizard._generate_lines()
        self.assertTrue(all(wizard.line_ids.mapped('is_new')))
        self.assertEqual(wizard.summary_prev_sales, 0.0)
        self.assertEqual(wizard.summary_sales_change, 0.0)

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------
    def test_08_group_by_sales_team(self):
        wizard = self._wizard(group_by='team')
        wizard._generate_lines()
        north = self._section(wizard, 'top', self.team_north)
        south = self._section(wizard, 'top', self.team_south)
        self.assertEqual(north.product_id, self.alpha + self.bravo)
        self.assertEqual(north.mapped('rank'), [1, 2])
        self.assertEqual(south.product_id, self.charlie + self.alpha)
        self.assertEqual(south.mapped('rank'), [1, 2], "Ranking restarts in each group")
        self.assertAlmostEqual(north[0].qty_sold, 10.0)
        self.assertAlmostEqual(south[1].qty_sold, 5.0)
        self.assertEqual(set(north.mapped('group_sequence')), {1}, "Team with the largest sales comes first")
        self.assertEqual(set(north.mapped('group_label')), {'TLS North'})

        groups = wizard._get_report_groups()
        self.assertEqual([g['label'] for g in groups], ['TLS North', 'TLS South'])
        self.assertAlmostEqual(groups[0]['top_totals']['sales'], 350.0)
        self.assertAlmostEqual(groups[0]['top_totals']['profit'], 230.0)

    def test_09_group_by_salesperson_with_comparison(self):
        wizard = self._wizard(group_by='user', compare_mode='previous_period')
        wizard._generate_lines()
        salesman_alpha = wizard.line_ids.filtered(
            lambda l: l.section == 'top' and l.user_id == self.salesman and l.product_id == self.alpha)
        manager_alpha = wizard.line_ids.filtered(
            lambda l: l.section == 'top' and l.user_id == self.manager and l.product_id == self.alpha)
        self.assertAlmostEqual(salesman_alpha.qty_sold, 10.0)
        self.assertAlmostEqual(salesman_alpha.prev_qty_sold, 20.0, msg="Previous figures are matched per group")
        self.assertAlmostEqual(salesman_alpha.qty_change_percent, -50.0, places=2)
        self.assertTrue(manager_alpha.is_new)

    def test_10_filters(self):
        wizard = self._wizard(team_ids=[Command.set(self.team_south.ids)])
        wizard._generate_lines()
        self.assertEqual(self._section(wizard, 'top').product_id, self.charlie + self.alpha)
        self.assertAlmostEqual(wizard.summary_sales, 118.0)

        wizard = self._wizard(user_ids=[Command.set(self.salesman.ids)])
        wizard._generate_lines()
        self.assertAlmostEqual(wizard.summary_sales, 350.0)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def test_11_validation(self):
        with self.assertRaises(ValidationError):
            self._wizard(date_from=date(2026, 4, 1), date_to=date(2026, 3, 1))
        with self.assertRaises(ValidationError):
            self._wizard(limit=0)
        with self.assertRaises(ValidationError):
            self._wizard(compare_mode='custom', compare_date_from=date(2026, 2, 20),
                         compare_date_to=date(2026, 2, 1))
        with self.assertRaises(ValidationError):
            self._wizard(compare_mode='custom')

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------
    def test_12_browser_action(self):
        wizard = self._wizard(compare_mode='previous_period', group_by='team')
        action = wizard.action_show_browser()
        self.assertEqual(action['res_model'], 'top.least.selling.report.line')
        self.assertEqual(action['domain'], [('wizard_id', '=', wizard.id)])
        self.assertEqual([view_type for _view_id, view_type in action['views']], ['list', 'pivot', 'graph'])
        self.assertEqual(action['views'][0][0],
                         self.env.ref('top_least_selling_report.view_top_least_selling_line_tree_compare').id)
        self.assertIn('search_default_group_team', action['context'])
        lines = self.env['top.least.selling.report.line'].search(action['domain'])
        self.assertEqual(lines, wizard.line_ids)
        # The pivot view aggregates correctly.
        data = self.env['top.least.selling.report.line'].read_group(
            action['domain'] + [('section', '=', 'top')], ['sales_amount:sum'], [])
        self.assertAlmostEqual(data[0]['sales_amount'], 468.0)

    def test_13_regeneration_replaces_lines(self):
        wizard = self._wizard()
        wizard._generate_lines()
        first_count = len(wizard.line_ids)
        wizard._generate_lines()
        self.assertEqual(len(wizard.line_ids), first_count)

    def test_14_pdf_report_english(self):
        wizard = self._wizard(compare_mode='previous_period').with_context(lang='en_US')
        wizard._generate_lines()
        html, _fmt = self.env['ir.actions.report'].with_context(lang='en_US')._render_qweb_html(
            'top_least_selling_report.action_report_top_least_selling', wizard.ids)
        html = html.decode() if isinstance(html, bytes) else str(html)
        self.assertIn('dir="ltr"', html)
        self.assertIn('Top Selling Products', html)
        self.assertIn('Least Selling Products', html)
        self.assertIn('TLS Alpha', html)
        self.assertIn('Prev. Rank', html)
        self.assertIn('tls-table', html)
        self.assertIn('62.82%', html, "Overall margin KPI is rendered")
        self.assertIn('+100.00%', html, "Signed change percentages are rendered")

    def test_14a_percent_helper_and_no_double_percent_in_xml(self):
        """Odoo's XML loader collapses '%%' to '%' in archs: keep formatting in Python."""
        Wizard = self.env['top.least.selling.wizard']
        self.assertEqual(Wizard._format_percent(62.8205), '62.82%')
        self.assertEqual(Wizard._format_percent(-26.666, signed=True), '-26.67%')
        self.assertEqual(Wizard._format_percent(100, signed=True), '+100.00%')
        self.assertEqual(Wizard._format_percent(False), '0.00%')
        from odoo.tools import file_open
        for path in ('report/top_least_selling_report_templates.xml',
                     'views/top_least_selling_line_views.xml',
                     'wizard/top_least_selling_wizard_views.xml'):
            with file_open('top_least_selling_report/' + path) as xml_file:
                self.assertNotIn('%%', xml_file.read(), path)

    def test_14b_pdf_anti_overlap_rules(self):
        report = self.env.ref('top_least_selling_report.action_report_top_least_selling')
        paper = report.paperformat_id
        self.assertEqual(paper, self.env.ref('top_least_selling_report.paperformat_top_least_selling'))
        self.assertGreater(paper.margin_top, paper.header_spacing,
                           "The body must start below the repeated layout header")
        css = self._report_css()
        self.assertIn('display: table-header-group', css)
        self.assertIn('page-break-inside: avoid', css)

    def test_15_excel_export_english(self):
        wizard = self._wizard(compare_mode='previous_period', group_by='team').with_context(lang='en_US')
        action = wizard.action_export_excel()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('field=excel_file', action['url'])
        self.assertTrue(wizard.excel_filename.endswith('.xlsx'))
        sheet, strings = self._read_xlsx(wizard)
        self.assertNotIn('rightToLeft="1"', sheet)
        for text in ('Top Selling Products', 'Least Selling Products', 'Sold Quantity Cost',
                     'Total Sale Price', 'Total Profit', 'TLS Alpha', 'TLS North'):
            self.assertIn(text, strings)

    # ------------------------------------------------------------------
    # Arabic (ar_001)
    # ------------------------------------------------------------------
    def _activate_arabic(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['top_least_selling_report'], ['ar_001'], overwrite=True)

    def test_16_pdf_report_arabic_rtl(self):
        self._activate_arabic()
        wizard = self._wizard(compare_mode='previous_period').with_context(lang='ar_001')
        wizard._generate_lines()
        self.assertEqual(wizard._get_report_direction(), 'rtl')
        html, _fmt = self.env['ir.actions.report'].with_context(lang='ar_001')._render_qweb_html(
            'top_least_selling_report.action_report_top_least_selling', wizard.ids)
        html = html.decode() if isinstance(html, bytes) else str(html)
        self.assertIn('dir="rtl"', html)
        self.assertIn('tls-rtl', html)
        self.assertIn(ARABIC_TOP_TITLE, html)
        self.assertIn(ARABIC_COST_HEADER, html)
        self.assertNotIn('Top Selling Products', html)

    def test_17_excel_export_arabic_rtl(self):
        self._activate_arabic()
        wizard = self._wizard().with_context(lang='ar_001')
        wizard.action_export_excel()
        sheet, strings = self._read_xlsx(wizard)
        self.assertIn('rightToLeft="1"', sheet)
        self.assertIn(ARABIC_TOP_TITLE, strings)
        self.assertIn(ARABIC_COST_HEADER, strings)

    def test_18_arabic_labels(self):
        self._activate_arabic()
        wizard = self._wizard(rank_by='profit').with_context(lang='ar_001')
        self.assertEqual(wizard._get_selection_label('rank_by'), 'إجمالي الربح')
        field_label = self.env['ir.model.fields'].with_context(lang='ar_001')._get(
            'top.least.selling.report.line', 'cost_amount').field_description
        self.assertEqual(field_label, ARABIC_COST_HEADER)
        # Latin product names keep their left-to-right order inside the RTL report.
        self.assertEqual(wizard._bidi_text('[FURN_8220] Desk'), '‪[FURN_8220] Desk‬')
        self.assertEqual(wizard._bidi_text('مكتب'), 'مكتب')
        self.assertEqual(wizard.with_context(lang='en_US')._bidi_text('[FURN_8220] Desk'), '[FURN_8220] Desk')
        self.assertEqual(wizard._bidi_text(False), '')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _read_xlsx(wizard):
        content = base64.b64decode(wizard.excel_file)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            sheet = archive.read('xl/worksheets/sheet1.xml').decode()
            strings = archive.read('xl/sharedStrings.xml').decode()
        return sheet, strings

    @staticmethod
    def _report_css():
        from odoo.tools import file_open
        with file_open('top_least_selling_report/static/src/scss/top_least_selling_report.scss') as scss:
            return scss.read()
