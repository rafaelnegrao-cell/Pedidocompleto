# -*- coding: utf-8 -*-
"""
Exportacao do arquivo 'Analise de Margem' com identidade visual N1.

Paleta institucional (Paleta_de_cores_e_fontes):
  Verde Primario #008D67 (cabecalho) · Verde escuro #006B4F
  Branco #FFFFFF (fundo) · Cinza Carvao #333333 (texto)
  Cinza Gelo #E9ECEF (bordas) · Zebra #F8F9FA
  Semaforos: Sucesso #28A745 · Atencao #FFC107 · Risco #DC3545
  Fonte: Arial
"""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Paleta N1
VERDE_PRIMARIO = "008D67"
VERDE_ESCURO = "006B4F"
BRANCO = "FFFFFF"
INK = "333333"           # texto principal
CINZA_GELO = "E9ECEF"    # bordas
ZEBRA = "F8F9FA"
RISCO = "DC3545"         # prejuizo
RISCO_FILL = "FAECE7"    # fundo de linha com MC negativa
FONTE = "Arial"

FMT_MOEDA = u'"R$" #,##0.00'
FMT_PCT = '0.00%'


def export_excel(df, meta, out_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Análise de Margem"
    ws.sheet_view.showGridLines = False

    cols = list(df.columns)
    money = set(meta.get("money_cols", []))
    pct = set(meta.get("pct_cols", []))
    mc_nom_col = "Margem de Contribuição Nominal (MC$)"
    mc_pct_col = "Margem de Contribuição Percentual (MC%)"

    header_fill = PatternFill("solid", fgColor=VERDE_PRIMARIO)
    header_font = Font(color=BRANCO, bold=True, size=9, name=FONTE)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    neg_fill = PatternFill("solid", fgColor=RISCO_FILL)
    thin = Side(style="thin", color=CINZA_GELO)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hborder = Border(left=Side(style="thin", color=BRANCO),
                     right=Side(style="thin", color=BRANCO),
                     top=Side(style="thin", color=BRANCO),
                     bottom=Side(style="thin", color=BRANCO))

    # cabecalho
    for j, col in enumerate(cols, start=1):
        c = ws.cell(row=1, column=j, value=str(col))
        c.fill = header_fill
        c.font = header_font
        c.alignment = header_align
        c.border = hborder
    ws.freeze_panes = "A2"

    mc_idx = cols.index(mc_nom_col) if mc_nom_col in cols else None
    for i, (_, row) in enumerate(df.iterrows(), start=2):
        mc_val = None
        if mc_idx is not None:
            try:
                mc_val = float(row[mc_nom_col])
            except Exception:
                mc_val = None
        negativo = (mc_val is not None and mc_val < 0)
        for j, col in enumerate(cols, start=1):
            val = row[col]
            if col in money or col in pct:
                try:
                    val = float(val)
                except Exception:
                    val = 0.0
            c = ws.cell(row=i, column=j, value=val)
            c.border = border
            # texto base Arial cinza carvao
            base_color = INK
            base_bold = False
            # destaca MC$ e MC% em vermelho quando prejuizo
            if negativo and col in (mc_nom_col, mc_pct_col):
                base_color = RISCO
                base_bold = True
            c.font = Font(name=FONTE, size=9, color=base_color, bold=base_bold)
            if col in money:
                c.number_format = FMT_MOEDA
            elif col in pct:
                c.number_format = FMT_PCT
            if negativo:
                c.fill = neg_fill
            elif i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=ZEBRA)

    # largura autoajustada
    for j, col in enumerate(cols, start=1):
        letter = get_column_letter(j)
        max_len = len(str(col))
        for i in range(2, ws.max_row + 1):
            v = ws.cell(row=i, column=j).value
            if v is None:
                continue
            txt = f"{v:,.2f}" if isinstance(v, float) else str(v)
            max_len = max(max_len, len(txt))
        ws.column_dimensions[letter].width = min(max(max_len + 3, 10), 48)

    ws.row_dimensions[1].height = 30
    wb.save(out_path)
    return out_path
