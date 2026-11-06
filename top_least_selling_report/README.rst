===================================
Top & Least Selling Products Report
===================================

Odoo 19 (Community & Enterprise). Author: Ibrahim Yahia.

Usage
=====
Sales > Reporting > **Top & Least Selling Products**. Odoo's own sales reports are left untouched.

Wizard options

* Start / End date (local time zone of the user).
* Compare with: No Comparison, Previous Period (same length, just before), Same Period Last
  Year, or Custom Period.
* Rank by Sold Quantity, Total Sale Price or Total Profit; number of products per set (1-1000).
* Group by Sales Team or Salesperson (the ranking restarts in each group, groups ordered by sales).
* Include saleable products without any sale in the least selling set (no grouping only).
* Filters: companies, sales teams, salespersons, product categories (with sub-categories).

Outputs

* **Show on Browser**: list (with comparison columns when comparing), pivot and graph views.
* **Print PDF**: A4 landscape report with criteria block, KPI cards and both ranking tables.
* **Export Excel**: .xlsx with the same content; right-to-left sheet for Arabic users.

How figures are computed
========================
* Source: confirmed sales orders (state *Sales Order*, locked or not) through ``sale.report``,
  aggregated in PostgreSQL. Point-of-sale orders are not included.
* Sold Quantity is converted to the product's reference unit of measure.
* Total Sale Price is the untaxed subtotal; Sold Quantity Cost is the cost stored on the sales
  order line (``sale_margin``); Total Profit = Total Sale Price - Sold Quantity Cost.
* Amounts are converted to the current company currency.
* Change % = (current - previous) / |previous|. A product without figures in the comparison
  period is flagged *New* instead of showing an infinite change.

PDF layout notes
================
The paper format reserves 44 mm on top with a 38 mm header spacing so the layout header never
overlaps the body; table headers repeat on every page, rows never split across pages and the
totals row does not repeat. Direction-dependent alignment uses inline styles so the RTL report
bundle served to Arabic users does not flip it twice.

Tests
=====
::

    odoo-bin -d <db> -i top_least_selling_report --test-enable --test-tags /top_least_selling_report --stop-after-init
