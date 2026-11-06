# -*- coding: utf-8 -*-
{
    'name': 'Top & Least Selling Products Report',
    'version': '17.0.1.0.0',
    'summary': 'Rank top and least selling products by quantity, revenue or profit '
               'with period comparison, team/salesperson grouping, browser, PDF and Excel output.',
    'description': """
Top & Least Selling Products Report
===================================
* Dedicated wizard under Sales > Reporting (default Odoo reports are untouched).
* Rank products by sold quantity, total sale price or total profit.
* Custom date range plus comparison against the previous period, the same
  period last year or any custom period.
* Optional grouping by Sales Team or Salesperson (ranking restarts per group).
* Columns: Sold Quantity, Unit of Measure, Sold Quantity Cost, Total Sale Price,
  Total Profit and Margin %, for both the top and the least selling sets.
* Three outputs: interactive list / pivot / graph, modern PDF, Excel (.xlsx).
* Full Arabic (ar_001) translation with right-to-left PDF and Excel layout.
* Aggregation is pushed to PostgreSQL through the standard sales analysis view,
  so it stays fast on large databases.
""",
    'category': 'Sales/Sales',
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'sale_margin'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': [
        'security/ir.model.access.csv',
        'report/paperformat.xml',
        'report/top_least_selling_report_templates.xml',
        'views/top_least_selling_line_views.xml',
        'wizard/top_least_selling_wizard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'top_least_selling_report/static/src/scss/top_least_selling_report.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
