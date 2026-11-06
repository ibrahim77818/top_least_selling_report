# -*- coding: utf-8 -*-
from odoo import fields, models


class TopLeastSellingReportLine(models.TransientModel):
    _name = 'top.least.selling.report.line'
    _description = 'Top & Least Selling Report Line'
    _rec_name = 'product_id'
    _order = 'group_sequence, section desc, rank, id'

    wizard_id = fields.Many2one(
        'top.least.selling.wizard', string='Report', required=True, ondelete='cascade', index=True)
    section = fields.Selection(
        [('top', 'Top Selling'), ('least', 'Least Selling')], string='Ranking', required=True, index=True)
    rank = fields.Integer(string='Rank', aggregator='min')
    group_sequence = fields.Integer(string='Group Sequence', aggregator='min')
    group_label = fields.Char(string='Group')
    team_id = fields.Many2one('crm.team', string='Sales Team', index=True)
    user_id = fields.Many2one('res.users', string='Salesperson', index=True)
    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)
    product_categ_id = fields.Many2one(
        'product.category', string='Product Category', related='product_id.categ_id', store=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    currency_id = fields.Many2one('res.currency', string='Currency')

    qty_sold = fields.Float(string='Sold Quantity', digits='Product Unit of Measure')
    cost_amount = fields.Monetary(string='Sold Quantity Cost', currency_field='currency_id')
    sales_amount = fields.Monetary(string='Total Sale Price', currency_field='currency_id')
    profit_amount = fields.Monetary(string='Total Profit', currency_field='currency_id')
    margin_percent = fields.Float(string='Margin (%)', digits=(16, 2), aggregator='avg')

    prev_qty_sold = fields.Float(string='Previous Quantity', digits='Product Unit of Measure')
    prev_cost_amount = fields.Monetary(string='Previous Cost', currency_field='currency_id')
    prev_sales_amount = fields.Monetary(string='Previous Sales', currency_field='currency_id')
    prev_profit_amount = fields.Monetary(string='Previous Profit', currency_field='currency_id')
    qty_change_percent = fields.Float(string='Quantity Change (%)', digits=(16, 2), aggregator='avg')
    sales_change_percent = fields.Float(string='Sales Change (%)', digits=(16, 2), aggregator='avg')
    profit_change_percent = fields.Float(string='Profit Change (%)', digits=(16, 2), aggregator='avg')
    prev_rank = fields.Integer(string='Previous Rank', aggregator='min')
    is_new = fields.Boolean(string='New in Period')
