# -*- coding: utf-8 -*-
import base64
import re
from collections import OrderedDict
from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date

from ..utils import report_engine, xlsx_builder

GROUP_FIELDS = {'team': 'team_id', 'user': 'user_id'}
MAX_LIMIT = 1000
RTL_CHARS = re.compile('[֐-ࣿיִ-﷿ﹰ-ﻼ]')


class TopLeastSellingWizard(models.TransientModel):
    _name = 'top.least.selling.wizard'
    _description = 'Top & Least Selling Products Report Wizard'

    # ------------------------------------------------------------------
    # Criteria
    # ------------------------------------------------------------------
    date_from = fields.Date(
        string='Start Date', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        string='End Date', required=True, default=fields.Date.context_today)
    compare_mode = fields.Selection(
        [('none', 'No Comparison'),
         ('previous_period', 'Previous Period'),
         ('previous_year', 'Same Period Last Year'),
         ('custom', 'Custom Period')],
        string='Compare With', required=True, default='none',
        help='Compare every product with its figures in another period: the period of the same '
             'length just before, the same dates one year earlier, or dates you choose.')
    compare_date_from = fields.Date(
        string='Comparison Start Date', compute='_compute_compare_dates', store=True, readonly=False)
    compare_date_to = fields.Date(
        string='Comparison End Date', compute='_compute_compare_dates', store=True, readonly=False)
    rank_by = fields.Selection(
        [('quantity', 'Sold Quantity'),
         ('revenue', 'Total Sale Price'),
         ('profit', 'Total Profit')],
        string='Rank By', required=True, default='quantity',
        help='Measure used to order the products. Quantities are expressed in each product\'s '
             'own unit of measure, so ranking by quantity is best used within similar products.')
    limit = fields.Integer(
        string='Number of Products', required=True, default=10,
        help='How many products are listed in the top set and in the least set (per group).')
    group_by = fields.Selection(
        [('none', 'No Grouping'),
         ('team', 'Sales Team'),
         ('user', 'Salesperson')],
        string='Group By', required=True, default='none')
    include_zero_sales = fields.Boolean(
        string='Include Products Without Sales',
        help='Saleable products that were not sold at all in the period appear first in the '
             'least selling set.')
    company_ids = fields.Many2many(
        'res.company', string='Companies', default=lambda self: self.env.companies)
    team_ids = fields.Many2many('crm.team', string='Sales Teams')
    user_ids = fields.Many2many('res.users', string='Salespersons', domain=[('share', '=', False)])
    categ_ids = fields.Many2many('product.category', string='Product Categories')
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    line_ids = fields.One2many('top.least.selling.report.line', 'wizard_id', string='Report Lines')
    summary_product_count = fields.Integer(string='Products Sold')
    summary_cost = fields.Monetary(string='Total Cost')
    summary_sales = fields.Monetary(string='Total Sales')
    summary_profit = fields.Monetary(string='Total Profit')
    summary_margin_percent = fields.Float(string='Overall Margin (%)', digits=(16, 2))
    summary_prev_sales = fields.Monetary(string='Previous Total Sales')
    summary_prev_profit = fields.Monetary(string='Previous Total Profit')
    summary_sales_change = fields.Float(string='Sales Change (%)', digits=(16, 2))
    summary_profit_change = fields.Float(string='Profit Change (%)', digits=(16, 2))
    excel_file = fields.Binary(string='Excel File', readonly=True)
    excel_filename = fields.Char(string='Excel File Name', readonly=True)

    # ------------------------------------------------------------------
    # Compute / constraints
    # ------------------------------------------------------------------
    @api.depends('compare_mode', 'date_from', 'date_to')
    def _compute_compare_dates(self):
        for wizard in self:
            if wizard.compare_mode in ('previous_period', 'previous_year') and wizard.date_from and wizard.date_to:
                if wizard.compare_mode == 'previous_period':
                    dates = report_engine.previous_period(wizard.date_from, wizard.date_to)
                else:
                    dates = report_engine.previous_year(wizard.date_from, wizard.date_to)
                wizard.compare_date_from, wizard.compare_date_to = dates
            elif wizard.compare_mode == 'custom':
                wizard.compare_date_from = wizard.compare_date_from
                wizard.compare_date_to = wizard.compare_date_to
            else:
                wizard.compare_date_from = False
                wizard.compare_date_to = False

    @api.constrains('date_from', 'date_to', 'compare_mode', 'compare_date_from', 'compare_date_to', 'limit')
    def _check_parameters(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_("The start date must be earlier than or equal to the end date."))
            if wizard.compare_mode != 'none':
                if not (wizard.compare_date_from and wizard.compare_date_to):
                    raise ValidationError(_("Please set both dates of the comparison period."))
                if wizard.compare_date_from > wizard.compare_date_to:
                    raise ValidationError(_(
                        "The comparison start date must be earlier than or equal to the comparison end date."))
            if wizard.limit < 1 or wizard.limit > MAX_LIMIT:
                raise ValidationError(_(
                    "The number of products must be between 1 and %s.", MAX_LIMIT))

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------
    def _get_group_field(self):
        self.ensure_one()
        return GROUP_FIELDS.get(self.group_by)

    def _get_utc_bounds(self, date_from, date_to):
        """Convert a local [date_from, date_to] day range into naive UTC datetimes."""
        tz = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        start = tz.localize(datetime.combine(date_from, time.min)).astimezone(pytz.UTC)
        end = tz.localize(datetime.combine(date_to, time.max)).astimezone(pytz.UTC)
        return start.replace(tzinfo=None), end.replace(tzinfo=None, microsecond=0)

    def _get_sale_report_domain(self, date_from, date_to):
        self.ensure_one()
        start, end = self._get_utc_bounds(date_from, date_to)
        companies = self.company_ids or self.env.companies
        domain = [
            ('date', '>=', start),
            ('date', '<=', end),
            ('state', '=', 'sale'),
            ('product_id', '!=', False),
            ('company_id', 'in', companies.ids),
        ]
        if self.team_ids:
            domain.append(('team_id', 'in', self.team_ids.ids))
        if self.user_ids:
            domain.append(('user_id', 'in', self.user_ids.ids))
        if self.categ_ids:
            domain.append(('categ_id', 'child_of', self.categ_ids.ids))
        return domain

    def _fetch_sales_rows(self, date_from, date_to):
        """Aggregate confirmed sales per (group,) product inside PostgreSQL.

        ``sale.report`` already converts quantities to the product's reference
        unit of measure and amounts to the company currency.
        """
        self.ensure_one()
        group_field = self._get_group_field()
        groupby = ([group_field] if group_field else []) + ['product_id']
        # read_group() is deprecated in 19.0: _read_group() returns one tuple per
        # group, (group records..., aggregates...), with the record rules applied.
        data = self.env['sale.report']._read_group(
            self._get_sale_report_domain(date_from, date_to),
            groupby,
            ['product_uom_qty:sum', 'price_subtotal:sum', 'margin:sum'],
        )
        empty_label = {'team_id': _("No Sales Team"), 'user_id': _("No Salesperson")}.get(group_field)
        rows = []
        for item in data:
            if group_field:
                group, product, qty, sales, margin = item
            else:
                group = None
                product, qty, sales, margin = item
            if not product:
                continue
            group_id, group_name = False, False
            if group_field:
                group_id = group.id if group else False
                group_name = group.display_name if group else empty_label
            rows.append({
                'group_id': group_id,
                'group_name': group_name,
                'product_id': product.id,
                'product_name': product.display_name,
                'uom_id': product.uom_id.id,
                'qty': qty or 0.0,
                'sales': sales or 0.0,
                'margin': margin or 0.0,
            })
        return rows

    def _fetch_zero_sales_rows(self, sold_product_ids):
        """Saleable products without any sale; only ``limit`` are needed."""
        self.ensure_one()
        companies = self.company_ids or self.env.companies
        domain = [
            ('sale_ok', '=', True),
            ('id', 'not in', list(sold_product_ids)),
            '|', ('company_id', '=', False), ('company_id', 'in', companies.ids),
        ]
        if self.categ_ids:
            domain.append(('categ_id', 'child_of', self.categ_ids.ids))
        products = self.env['product.product'].search(domain, limit=self.limit)
        return [{
            'group_id': False,
            'group_name': False,
            'product_id': product.id,
            'product_name': product.display_name,
            'uom_id': product.uom_id.id,
            'qty': 0.0,
            'sales': 0.0,
            'margin': 0.0,
            'zero_fill': True,
        } for product in products]

    def _generate_lines(self):
        """(Re)compute the report lines and the summary figures."""
        self.ensure_one()
        self.line_ids.unlink()
        current = self._fetch_sales_rows(self.date_from, self.date_to)
        if self.include_zero_sales and self.group_by == 'none':
            current += self._fetch_zero_sales_rows({row['product_id'] for row in current})
        previous = None
        if self.compare_mode != 'none':
            previous = self._fetch_sales_rows(self.compare_date_from, self.compare_date_to)

        result = report_engine.build_report(current, previous, self.rank_by, self.limit)
        group_field = self._get_group_field()
        vals_list = []
        for line in result['lines']:
            vals = {
                'wizard_id': self.id,
                'section': line['section'],
                'rank': line['rank'],
                'group_sequence': line['group_sequence'],
                'group_label': line['group_name'] or False,
                'product_id': line['product_id'],
                'uom_id': line['uom_id'],
                'currency_id': self.currency_id.id,
                'qty_sold': line['qty'],
                'cost_amount': line['cost'],
                'sales_amount': line['sales'],
                'profit_amount': line['profit'],
                'margin_percent': line['margin_pct'],
                'prev_qty_sold': line['prev_qty'],
                'prev_cost_amount': line['prev_cost'],
                'prev_sales_amount': line['prev_sales'],
                'prev_profit_amount': line['prev_profit'],
                'qty_change_percent': line['qty_change'],
                'sales_change_percent': line['sales_change'],
                'profit_change_percent': line['profit_change'],
                'prev_rank': line['prev_rank'],
                'is_new': line['is_new'],
            }
            if group_field:
                vals[group_field] = line['group_id'] or False
            vals_list.append(vals)
        self.env['top.least.selling.report.line'].create(vals_list)

        summary = result['summary']
        self.write({
            'summary_product_count': summary['product_count'],
            'summary_cost': summary['cost'],
            'summary_sales': summary['sales'],
            'summary_profit': summary['profit'],
            'summary_margin_percent': summary['margin_pct'],
            'summary_prev_sales': summary['prev_sales'],
            'summary_prev_profit': summary['prev_profit'],
            'summary_sales_change': summary['sales_change'],
            'summary_profit_change': summary['profit_change'],
        })
        self.invalidate_recordset(['line_ids'])
        return True

    # ------------------------------------------------------------------
    # Helpers used by the PDF template and the Excel export
    # ------------------------------------------------------------------
    def _get_selection_label(self, field_name):
        self.ensure_one()
        selection = self._fields[field_name]._description_selection(self.env)
        return dict(selection).get(self[field_name], '')

    @api.model
    def _format_percent(self, value, signed=False):
        """Percent label for the PDF.

        Formatting lives in Python on purpose: Odoo's XML loader turns '%%'
        into '%' in view archs, which breaks '%.2f%%' written in a template.
        """
        return ('%+.2f%%' if signed else '%.2f%%') % (value or 0.0)

    def _bidi_text(self, text):
        """Keep Latin text (e.g. '[FURN_8220] Four Person Desk') in left-to-right
        order inside a right-to-left report; otherwise the bidi algorithm moves
        the brackets around. Text that already contains Arabic is left as is."""
        text = text or ''
        if not text or self._get_report_direction() != 'rtl' or RTL_CHARS.search(text):
            return text
        return '‪%s‬' % text

    def _get_report_direction(self):
        code = self.env.lang or self.env.user.lang or 'en_US'
        lang = self.env['res.lang'].with_context(active_test=False).search([('code', '=', code)], limit=1)
        return (lang.direction if lang else 'ltr') or 'ltr'

    def _get_company_names(self):
        self.ensure_one()
        return ', '.join((self.company_ids or self.env.companies).mapped('name'))

    def _get_report_groups(self):
        """Lines organised per group then per section, with section totals."""
        self.ensure_one()
        empty = self.env['top.least.selling.report.line']
        groups = OrderedDict()
        for line in self.line_ids.sorted(lambda l: (l.group_sequence, l.section != 'top', l.rank, l.id)):
            group = groups.setdefault(line.group_sequence, {
                'label': line.group_label, 'top': empty, 'least': empty})
            group[line.section] |= line
        result = []
        for group in groups.values():
            for section in ('top', 'least'):
                lines = group[section]
                cost = sum(lines.mapped('cost_amount'))
                sales = sum(lines.mapped('sales_amount'))
                profit = sum(lines.mapped('profit_amount'))
                group[section + '_totals'] = {
                    'cost': cost, 'sales': sales, 'profit': profit,
                    'margin': report_engine.margin_percent(profit, sales),
                }
            result.append(group)
        return result

    def _format_period(self, date_from, date_to):
        return '%s - %s' % (format_date(self.env, date_from), format_date(self.env, date_to))

    def _prepare_xlsx_payload(self):
        self.ensure_one()
        compare = self.compare_mode != 'none'
        columns = [
            {'key': 'rank', 'label': _("Rank"), 'type': 'int', 'width': 8},
            {'key': 'product', 'label': _("Product"), 'type': 'text', 'width': 44},
            {'key': 'uom', 'label': _("Unit of Measure"), 'type': 'text', 'width': 16},
            {'key': 'qty', 'label': _("Sold Quantity"), 'type': 'qty', 'width': 15},
            {'key': 'cost', 'label': _("Sold Quantity Cost"), 'type': 'money', 'width': 18},
            {'key': 'sales', 'label': _("Total Sale Price"), 'type': 'money', 'width': 18},
            {'key': 'profit', 'label': _("Total Profit"), 'type': 'money', 'width': 18},
            {'key': 'margin', 'label': _("Margin %"), 'type': 'pct', 'width': 12},
        ]
        if compare:
            columns += [
                {'key': 'prev_qty', 'label': _("Previous Quantity"), 'type': 'qty', 'width': 15},
                {'key': 'prev_sales', 'label': _("Previous Sales"), 'type': 'money', 'width': 17},
                {'key': 'prev_profit', 'label': _("Previous Profit"), 'type': 'money', 'width': 17},
                {'key': 'qty_change', 'label': _("Quantity Change %"), 'type': 'pct', 'width': 14},
                {'key': 'sales_change', 'label': _("Sales Change %"), 'type': 'pct', 'width': 14},
                {'key': 'profit_change', 'label': _("Profit Change %"), 'type': 'pct', 'width': 14},
                {'key': 'prev_rank', 'label': _("Previous Rank"), 'type': 'center', 'width': 13},
            ]

        meta = [
            (_("Period"), self._format_period(self.date_from, self.date_to)),
            (_("Comparison Period"),
             self._format_period(self.compare_date_from, self.compare_date_to) if compare else _("None")),
            (_("Ranked By"), self._get_selection_label('rank_by')),
            (_("Products per Ranking"), str(self.limit)),
            (_("Grouped By"), self._get_selection_label('group_by')),
            (_("Companies"), self._get_company_names()),
            (_("Currency"), self.currency_id.name),
        ]
        summary = [
            (_("Products Sold"), self.summary_product_count, 'int'),
            (_("Total Sale Price"), self.summary_sales, 'money'),
            (_("Sold Quantity Cost"), self.summary_cost, 'money'),
            (_("Total Profit"), self.summary_profit, 'money'),
            (_("Overall Margin %"), self.summary_margin_percent, 'pct'),
        ]
        if compare:
            summary += [
                (_("Sales Change %"), self.summary_sales_change, 'pct'),
                (_("Profit Change %"), self.summary_profit_change, 'pct'),
            ]

        def line_row(line):
            row = {
                'rank': line.rank,
                'product': line.product_id.display_name,
                'uom': line.uom_id.name or '',
                'qty': line.qty_sold,
                'cost': line.cost_amount,
                'sales': line.sales_amount,
                'profit': line.profit_amount,
                'margin': line.margin_percent,
            }
            if compare:
                row.update({
                    'prev_qty': line.prev_qty_sold,
                    'prev_sales': line.prev_sales_amount,
                    'prev_profit': line.prev_profit_amount,
                    'qty_change': line.qty_change_percent,
                    'sales_change': line.sales_change_percent,
                    'profit_change': line.profit_change_percent,
                    'prev_rank': str(line.prev_rank) if line.prev_rank else (_("New") if line.is_new else '-'),
                })
            return row

        groups = []
        for group in self._get_report_groups():
            sections = []
            for kind, title in (('top', _("Top Selling Products")), ('least', _("Least Selling Products"))):
                totals = group[kind + '_totals']
                sections.append({
                    'kind': kind,
                    'title': title,
                    'rows': [line_row(line) for line in group[kind]],
                    'totals': {'cost': totals['cost'], 'sales': totals['sales'],
                               'profit': totals['profit'], 'margin': totals['margin']},
                    'total_label': _("Total"),
                })
            groups.append({'label': group['label'], 'sections': sections})

        return {
            'title': _("Top & Least Selling Products"),
            'sheet_name': _("Report"),
            'rtl': self._get_report_direction() == 'rtl',
            'meta': meta,
            'summary': summary,
            'columns': columns,
            'groups': groups,
            'empty_message': _("No sales found for the selected criteria."),
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_show_browser(self):
        self.ensure_one()
        self._generate_lines()
        compare = self.compare_mode != 'none'
        list_view = self.env.ref(
            'top_least_selling_report.view_top_least_selling_line_tree_compare' if compare
            else 'top_least_selling_report.view_top_least_selling_line_tree')
        context = {'search_default_group_section': 2}
        if self.group_by == 'team':
            context['search_default_group_team'] = 1
        elif self.group_by == 'user':
            context['search_default_group_user'] = 1
        return {
            'type': 'ir.actions.act_window',
            'name': _("Top & Least Selling Products"),
            'res_model': 'top.least.selling.report.line',
            'view_mode': 'list,pivot,graph',
            'views': [
                (list_view.id, 'list'),
                (self.env.ref('top_least_selling_report.view_top_least_selling_line_pivot').id, 'pivot'),
                (self.env.ref('top_least_selling_report.view_top_least_selling_line_graph').id, 'graph'),
            ],
            'search_view_id': self.env.ref('top_least_selling_report.view_top_least_selling_line_search').id,
            'domain': [('wizard_id', '=', self.id)],
            'context': context,
            'target': 'current',
        }

    def action_print_pdf(self):
        self.ensure_one()
        self._generate_lines()
        return self.env.ref('top_least_selling_report.action_report_top_least_selling').report_action(self)

    def action_export_excel(self):
        self.ensure_one()
        self._generate_lines()
        content = xlsx_builder.build_workbook(self._prepare_xlsx_payload())
        filename = 'top_least_selling_%s_%s.xlsx' % (self.date_from, self.date_to)
        self.write({'excel_file': base64.b64encode(content), 'excel_filename': filename})
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=%s&id=%s&field=excel_file&filename_field=excel_filename&download=true'
                   % (self._name, self.id),
            'target': 'self',
        }
