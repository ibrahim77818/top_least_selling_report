# -*- coding: utf-8 -*-
"""Excel (.xlsx) writer for the Top & Least Selling report.

Takes an already translated, plain-data payload so it has no Odoo dependency::

    {
        'title': str, 'sheet_name': str, 'rtl': bool,
        'meta': [(label, value), ...],
        'summary': [(label, value, type), ...],
        'columns': [{'key', 'label', 'type', 'width'}, ...],
        'groups': [{'label': str | False,
                    'sections': [{'kind': 'top' | 'least', 'title': str,
                                  'rows': [dict], 'totals': dict, 'total_label': str}]}],
        'empty_message': str,
    }

Column types: 'int', 'text', 'center' (centred text), 'qty', 'money', 'pct'.
"""
import io
import re

import xlsxwriter

NAVY = '#0F3D5C'
GREEN = '#1E7B4F'
AMBER = '#B45309'
ZEBRA = '#F9FAFB'
BORDER = '#D1D5DB'

NUMBER_FORMATS = {
    'int': '0',
    'qty': '#,##0.00',
    'money': '#,##0.00',
    'pct': '0.00"%"',
}


def _sheet_name(name):
    name = re.sub(r'[\[\]:*?/\\]', ' ', name or 'Report').strip() or 'Report'
    return name[:31]


def build_workbook(payload):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    rtl = bool(payload.get('rtl'))
    align = 'right' if rtl else 'left'

    def fmt(**kwargs):
        props = {'font_name': 'Arial', 'font_size': 10, 'valign': 'vcenter'}
        props.update(kwargs)
        if rtl:
            props.setdefault('reading_order', 2)
        return workbook.add_format(props)

    f_title = fmt(bold=True, font_size=16, font_color=NAVY, align=align)
    f_meta_label = fmt(bold=True, bg_color='#F3F6F9', font_color='#4B5563', border=1, border_color=BORDER, align=align)
    f_meta_value = fmt(border=1, border_color=BORDER, align=align)
    f_kpi_label = fmt(bold=True, font_color='#4B5563', bg_color='#F0F6FB', top=3, top_color='#0F6E9E',
                      align='center', text_wrap=True)
    f_group = fmt(bold=True, font_size=13, font_color=NAVY, bottom=2, bottom_color=NAVY, align=align)
    f_section = {
        'top': fmt(bold=True, font_size=11, font_color='#FFFFFF', bg_color=GREEN, align=align),
        'least': fmt(bold=True, font_size=11, font_color='#FFFFFF', bg_color=AMBER, align=align),
    }
    f_header = fmt(bold=True, font_color='#FFFFFF', bg_color=NAVY, border=1, border_color=NAVY,
                   align='center', text_wrap=True)
    f_empty = fmt(italic=True, font_color='#6B7280', align=align)

    cell_formats = {}
    for zebra in (False, True):
        for col_type in ('int', 'text', 'center', 'qty', 'money', 'pct'):
            props = {'border': 1, 'border_color': BORDER, 'indent': 1}
            if zebra:
                props['bg_color'] = ZEBRA
            if col_type == 'text':
                props['align'] = align
            elif col_type == 'center':
                props.update(align='center', indent=0)
            else:
                props['num_format'] = NUMBER_FORMATS[col_type]
                if col_type == 'int':
                    props.update(align='center', indent=0)
            cell_formats[(col_type, zebra)] = fmt(**props)
    total_formats = {
        col_type: fmt(bold=True, bg_color='#EEF2F6', top=2, top_color=NAVY, bottom=1, bottom_color=BORDER,
                      num_format=NUMBER_FORMATS.get(col_type, '@'), align=align if col_type == 'text' else 'right')
        for col_type in ('int', 'text', 'center', 'qty', 'money', 'pct')
    }
    kpi_values = {
        col_type: fmt(bold=True, font_size=13, font_color=NAVY, bg_color='#F0F6FB', align='center',
                      num_format=NUMBER_FORMATS.get(col_type, '@'))
        for col_type in ('int', 'text', 'qty', 'money', 'pct')
    }

    sheet = workbook.add_worksheet(_sheet_name(payload.get('sheet_name')))
    if rtl:
        sheet.right_to_left()
    sheet.set_landscape()
    sheet.set_paper(9)  # A4
    sheet.fit_to_pages(1, 0)
    sheet.hide_gridlines(2)
    sheet.set_margins(left=0.4, right=0.4, top=0.5, bottom=0.5)

    columns = payload['columns']
    last_col = len(columns) - 1
    for index, column in enumerate(columns):
        sheet.set_column(index, index, column.get('width', 14))

    def write_value(row, col, value, col_type, cell_format):
        if value is None or value is False:
            sheet.write_blank(row, col, None, cell_format)
        elif col_type in ('text', 'center'):
            sheet.write_string(row, col, str(value), cell_format)
        else:
            sheet.write_number(row, col, value, cell_format)

    def merged(row, text, cell_format, first=0, last=None):
        last = last_col if last is None else last
        if last > first:
            sheet.merge_range(row, first, row, last, text, cell_format)
        else:
            sheet.write(row, first, text, cell_format)

    row = 0
    merged(row, payload.get('title') or '', f_title)
    sheet.set_row(row, 28)
    row += 2

    # Labels span the two first columns (the rank column alone is too narrow).
    for label, value in payload.get('meta', []):
        merged(row, str(label), f_meta_label, first=0, last=min(1, last_col))
        merged(row, str(value), f_meta_value, first=min(2, last_col), last=min(4, last_col))
        row += 1
    row += 1

    summary = payload.get('summary', [])
    if summary:
        sheet.set_row(row, 30)
        for col, (label, _value, _type) in enumerate(summary[:last_col + 1]):
            sheet.write_string(row, col, str(label), f_kpi_label)
        row += 1
        sheet.set_row(row, 24)
        for col, (_label, value, col_type) in enumerate(summary[:last_col + 1]):
            write_value(row, col, value, col_type, kpi_values[col_type])
        row += 2

    groups = payload.get('groups', [])
    if not groups:
        merged(row, payload.get('empty_message') or '', f_empty)
        row += 1

    for group in groups:
        if group.get('label'):
            merged(row, str(group['label']), f_group)
            sheet.set_row(row, 22)
            row += 1
        for section in group.get('sections', []):
            merged(row, section['title'], f_section[section.get('kind', 'top')])
            sheet.set_row(row, 20)
            row += 1
            sheet.set_row(row, 30)
            for col, column in enumerate(columns):
                sheet.write_string(row, col, column['label'], f_header)
            row += 1
            if not section['rows']:
                merged(row, payload.get('empty_message') or '', f_empty)
                row += 1
            for index, data in enumerate(section['rows']):
                zebra = bool(index % 2)
                for col, column in enumerate(columns):
                    col_type = column['type']
                    write_value(row, col, data.get(column['key']), col_type, cell_formats[(col_type, zebra)])
                row += 1
            totals = section.get('totals') or {}
            for col, column in enumerate(columns):
                col_type = column['type']
                if col == 0:
                    sheet.write_string(row, col, section.get('total_label') or '', total_formats['text'])
                elif column['key'] in totals:
                    write_value(row, col, totals[column['key']], col_type, total_formats[col_type])
                else:
                    sheet.write_blank(row, col, None, total_formats['text'])
            row += 2

    workbook.close()
    return output.getvalue()
