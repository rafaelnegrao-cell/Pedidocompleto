# -*- coding: utf-8 -*-
"""
Processador de Margem de Contribuicao - Eixo N1.

Cruza A Faturar x N1_Config_Producao_Compilado:
  - Nome Curto  <- aba "Indice Linha x Produto" (fallback aba "Produtos")
  - MP          <- aba "Produtos" (coluna MP)
  - Linha envase<- aba "Indice Linha x Produto" (linhas compativeis por planta)
Join pelo CODIGO (prefixo numerico do "Produto" do pedido = coluna Codigo do Config).
Frete: CIF (Tipo Frete = Emitente) via Tabela de Rotas CIF; FOB (Destinatario) = 0.
"""
import re
import pandas as pd

from .columns import resolve, norm, to_number
from . import frete_cif

# =====================================================================
# COLUNAS DO ARQUIVO "A FATURAR"  (ajuste aqui se os cabecalhos mudarem)
# =====================================================================
COLMAP = {
    "pedido":        ["Pedido", "Nº Pedido", "Numero Pedido", "Cod Pedido"],
    "nome_produto":  ["Produto", "Nome do Produto", "Descricao do Produto",
                      "Descrição do Produto", "Descricao", "Mercadoria"],
    "valor":         ["Valor", "Valor Total", "Valor Venda", "Valor Faturado"],
    "uf_cliente":    ["Uf Cliente", "UF Cliente", "UF", "Uf Destino"],
    "cidade":        ["Cidade", "Municipio", "Cidade Cliente", "Cidade Destino"],
    "peso_total":    ["Peso Total", "Peso", "Peso Kg", "Peso Liquido"],
    "comissao_pct":  ["% Comissao", "Percentual Comissao", "Comissao %",
                      "Perc Comissao", "Comissao (%)"],
    "bonificacao":   ["Bonificacao R$", "Bonificacao", "Bonif R$", "Bonif"],
    "icms":          ["ICMS", "Valor ICMS", "ICMS R$"],
    "embalagem":     ["Embalagem", "Valor Embalagem", "Embalagem R$"],
    "desc_financ":   ["Desc Financ", "Desc Financeiro", "Desconto Financeiro",
                      "Desc. Financeiro", "Desc Fin"],
    "tipo_frete":    ["Tipo Frete", "Frete", "Modalidade Frete", "Tipo de Frete"],
    "filial":        ["Filial", "Empresa", "Estabelecimento", "Unidade",
                      "Razao Social", "Origem"],  # ex.: "MATRIZ - ACUCAR NUMERO UM"
}

# ---- TIPOS DE MP CANONICOS (coluna MP da aba Produtos) ----
CANONICAL_MP = [
    "DEMERARA", "IC45", "MALHA 30", "MASCAVO", "ND",
    "REFINADO AMORFO", "TIPO 1", "TIPO 2", "TIPO 3", "TIPO 4",
]


def _mp_key(s):
    return norm(s).replace(" ", "")


_CANON_BY_KEY = {_mp_key(m): m for m in CANONICAL_MP}
_CANON_ORDER = {m: i for i, m in enumerate(CANONICAL_MP)}


def canonicalize_mp(value):
    raw = str(value or "").strip()
    if not raw or raw.lower() == "nan":
        return ""
    return _CANON_BY_KEY.get(_mp_key(raw), raw.upper())


def _mp_sort_key(m):
    return (_CANON_ORDER.get(m, 999), m)


# ---- ICMS / origem ----
UF_ORIGEM_PADRAO = "PR"
ICMS_INTERNA = 0.07
ICMS_INTERESTADUAL = 0.12
_UF_SIGLAS = {"ac","al","ap","am","ba","ce","df","es","go","ma","mt","ms","mg",
              "pa","pb","pr","pe","pi","rj","rn","rs","ro","rr","sc","sp","se","to"}


def origem_uf_from_filial(value):
    """'MATRIZ - ACUCAR NUMERO UM'->PR (Sertanopolis) | 'SP - ...'->SP (Itaju)."""
    s = norm(value)
    if not s:
        return UF_ORIGEM_PADRAO
    if "matriz" in s or "sertanopolis" in s:
        return "PR"
    if "itaju" in s:
        return "SP"
    primeiro = s.split()[0] if s.split() else ""
    if primeiro in _UF_SIGLAS:
        return primeiro.upper()
    return UF_ORIGEM_PADRAO


def _plant_key_from_uf(uf):
    """PR -> SERT (Sertanopolis) | SP -> ITAJU."""
    return "SERT" if (uf or "").upper() == "PR" else "ITAJU"


def _plant_key_from_planta(value):
    s = norm(value)
    if "itaju" in s:
        return "ITAJU"
    if "sertanopolis" in s or "matriz" in s:
        return "SERT"
    return ""


# =====================================================================
#  Leitura de arquivos
# =====================================================================
def _read_any(path):
    p = path.lower()
    if p.endswith(".csv") or p.endswith(".txt"):
        for sep in (";", ",", "\t"):
            try:
                df = pd.read_csv(path, sep=sep, dtype=str, encoding="utf-8")
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue
        return pd.read_csv(path, dtype=str, encoding="latin-1")
    return pd.read_excel(path, dtype=str)


def _lead_code(s):
    """Codigo numerico no inicio do texto do produto. '51052-PA-...' -> '51052'."""
    m = re.match(r"\s*0*(\d+)", str(s or ""))
    return m.group(1) if m else ""


def _norm_code(v):
    if v is None:
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _load_config_sheet(config_path, name_terms):
    """Le uma aba do Config (por termos do nome) detectando a linha de cabecalho
    real (primeira linha que contem a celula 'Codigo')."""
    if config_path.lower().endswith((".csv", ".txt")):
        return None
    all_raw = pd.read_excel(config_path, sheet_name=None, header=None, dtype=str)
    target = None
    for sname, raw in all_raw.items():
        ns = norm(sname)
        if all(t in ns for t in name_terms):
            target = (sname, raw)
            break
    if target is None:
        return None
    sname, raw = target
    hrow = 0
    for i in range(min(15, len(raw))):
        if any(norm(x) == "codigo" for x in raw.iloc[i].tolist()):
            hrow = i
            break
    cols = [str(x) for x in raw.iloc[hrow].tolist()]
    df = raw.iloc[hrow + 1:].copy()
    df.columns = cols
    return df


def load_config_index(config_path):
    """
    Monta o indice de produtos por codigo:
      { codigo: {nome_curto, mp, linhas{ITAJU:set, SERT:set}} }
    e um mapa auxiliar nome_normalizado -> codigo (fallback de join).
    """
    by_cod, by_nome = {}, {}

    # aba Produtos -> MP + Nome Curto (+ nome completo)
    prod = _load_config_sheet(config_path, ["produtos"])
    if prod is not None and not prod.empty:
        c_cod = resolve(prod, ["Codigo"], required=False)
        c_mp = resolve(prod, COLMAP_CFG["mp"], required=False)
        c_nc = resolve(prod, COLMAP_CFG["nome_curto"], required=False)
        c_np = resolve(prod, ["Produto", "Nome do Produto"], required=False)
        for _, row in prod.iterrows():
            cod = _lead_code(row.get(c_cod)) if c_cod else ""
            if not cod:
                continue
            info = by_cod.setdefault(cod, {"nome_curto": "", "mp": "",
                                           "linhas": {"ITAJU": set(), "SERT": set()}})
            if c_mp:
                info["mp"] = canonicalize_mp(row.get(c_mp))
            if c_nc and not info["nome_curto"]:
                info["nome_curto"] = str(row.get(c_nc, "")).strip()
            if c_np:
                nm = norm(row.get(c_np))
                if nm:
                    by_nome.setdefault(nm, cod)

    # aba Indice Linha x Produto -> Nome Curto (preferencial) + linhas por planta
    idx = _load_config_sheet(config_path, ["indice", "produto"])
    if idx is not None and not idx.empty:
        c_cod = resolve(idx, ["Codigo"], required=False)
        c_nc = resolve(idx, COLMAP_CFG["nome_curto"], required=False)
        c_lin = resolve(idx, COLMAP_CFG["linha"], required=False)
        c_pl = resolve(idx, ["Planta", "Unidade"], required=False)
        c_np = resolve(idx, ["Nome do Produto", "Produto"], required=False)
        for _, row in idx.iterrows():
            cod = _lead_code(row.get(c_cod)) if c_cod else ""
            if not cod:
                continue
            info = by_cod.setdefault(cod, {"nome_curto": "", "mp": "",
                                           "linhas": {"ITAJU": set(), "SERT": set()}})
            if c_nc:
                nc = str(row.get(c_nc, "")).strip()
                if nc and nc.lower() != "nan":
                    info["nome_curto"] = nc  # Indice tem prioridade
            if c_lin and c_pl:
                linha = str(row.get(c_lin, "")).strip()
                pk = _plant_key_from_planta(row.get(c_pl))
                if linha and linha.lower() != "nan" and pk:
                    info["linhas"][pk].add(linha)
            if c_np:
                nm = norm(row.get(c_np))
                if nm:
                    by_nome.setdefault(nm, cod)

    if not by_cod:
        raise ValueError(
            "Nao foi possivel ler o Config (abas 'Produtos' e/ou "
            "'Indice Linha x Produto'). Verifique o arquivo.")
    return {"by_cod": by_cod, "by_nome": by_nome}


# variantes de cabecalho das abas do Config
COLMAP_CFG = {
    "mp":         ["MP", "Tipo Materia Prima", "Materia Prima", "Tipo MP",
                   "Materia-Prima", "Tipo de Materia Prima"],
    "nome_curto": ["Nome Curto", "Nome Reduzido", "Nome Abreviado", "Descricao Curta"],
    "linha":      ["Linha", "Linha Envase", "Linha de Envase", "Linha Producao"],
}


def _resolve_comissao_pct(orders):
    """Resolve a coluna de % de comissao. Como norm() remove o '%', a coluna
    '% Comissão' colidiria com 'Comissão' (R$); por isso exigimos o '%' no
    cabecalho original e evitamos a coluna de valor em R$."""
    for col in orders.columns:
        h = str(col).lower()
        if "%" in h and "comiss" in h:
            return col
    for col in orders.columns:
        h = norm(col)
        if "percent" in h and "comiss" in h:
            return col
    return resolve(orders, COLMAP["comissao_pct"], field_name="% Comissao")


def _match_info(cfg, nome_produto):
    """Localiza o produto no indice: por codigo (prefixo) e, se falhar, por nome."""
    cod = _lead_code(nome_produto)
    info = cfg["by_cod"].get(cod) if cod else None
    if info is None:
        cod2 = cfg["by_nome"].get(norm(nome_produto))
        if cod2:
            info = cfg["by_cod"].get(cod2)
    return info


def load_priority_set(priority_path):
    df = _read_any(priority_path)
    if df.empty:
        return set()
    col = df.columns[0]
    return {_norm_code(v) for v in df[col].tolist()
            if v is not None and str(v).strip() and str(v).strip().lower() != "nan"}


# =====================================================================
#  Etapa 1+2: analise
# =====================================================================
def mp_types_from_config(config_path):
    """Lista os tipos de MP cadastrados no Config (aba Produtos), em ordem canonica.
    Usado para montar os campos de custo ANTES de carregar os pedidos."""
    cfg = load_config_index(config_path)
    mps = {info["mp"] for info in cfg["by_cod"].values() if info.get("mp")}
    return sorted(mps, key=_mp_sort_key)


def diagnostics(df):
    """Avisos derivados do resultado: produtos sem cadastro e cidades sem rota CIF."""
    semmp = df["Tipo de Matéria Prima"].fillna("").astype(str).str.strip() == ""
    sem_rota = (df["Tipo Frete"].astype(str) == "CIF") & \
               (df["Destino da Rota"].fillna("").astype(str).str.strip() == "")
    return {
        "n_sem_config": int(semmp.sum()),
        "produtos_sem_config": sorted(
            df.loc[semmp, "Produto"].dropna().astype(str).str.strip().unique().tolist()
        )[:50] if "Produto" in df.columns else [],
        "n_cidades_sem_rota": int(sem_rota.sum()),
    }


def analyze(orders_path, config_path, priority_path, cif_path=None):
    orders = _read_any(orders_path)
    if orders.empty:
        raise ValueError("O arquivo A Faturar esta vazio.")

    np_col = resolve(orders, COLMAP["nome_produto"], field_name="Produto")
    cfg = load_config_index(config_path)
    prioridade = load_priority_set(priority_path)

    mp_set, sem_config = set(), set()
    for _, row in orders.iterrows():
        produto = row.get(np_col)
        info = _match_info(cfg, produto)
        if info and info.get("mp"):
            mp_set.add(info["mp"])
        elif produto and str(produto).strip().lower() != "nan":
            sem_config.add(str(produto).strip())

    cif = frete_cif.load_cif_table(cif_path or config_path)
    cidade_col = resolve(orders, COLMAP["cidade"], required=False)
    cidades_sem_rota = set()
    if cif and cidade_col:
        for _, row in orders.iterrows():
            cidade = row.get(cidade_col)
            if not frete_cif.has_city(cif, cidade):
                cidades_sem_rota.add(str(cidade).strip())

    return {
        "mp_types": sorted(mp_set, key=_mp_sort_key),
        "mp_nao_reconhecidos": sorted(m for m in mp_set if m not in _CANON_ORDER),
        "n_pedidos": int(len(orders)),
        "n_priorizados": int(len(prioridade)),
        "sem_config": sorted(sem_config)[:50],
        "n_sem_config": len(sem_config),
        "cif_ok": bool(cif),
        "cif_faixas": len(cif["bands"]) if cif else 0,
        "cidades_sem_rota": sorted(c for c in cidades_sem_rota
                                   if c and c.lower() != "nan")[:50],
    }


# =====================================================================
#  Etapa 3: processamento + calculo de margem
# =====================================================================
def process(orders_path, config_path, priority_path, custos_saca, cif_path=None):
    orders = _read_any(orders_path)
    cfg = load_config_index(config_path)
    prioridade = load_priority_set(priority_path)
    cif = frete_cif.load_cif_table(cif_path or config_path)

    custo_kg = {mp: to_number(v) / 50.0 for mp, v in custos_saca.items()}

    np_col = resolve(orders, COLMAP["nome_produto"], field_name="Produto")
    valor_col = resolve(orders, COLMAP["valor"], field_name="Valor")
    uf_col = resolve(orders, COLMAP["uf_cliente"], field_name="UF Cliente")
    peso_col = resolve(orders, COLMAP["peso_total"], field_name="Peso Total")
    com_col = _resolve_comissao_pct(orders)
    cidade_col = resolve(orders, COLMAP["cidade"], required=False)
    bonif_col = resolve(orders, COLMAP["bonificacao"], required=False)
    pedido_col = resolve(orders, COLMAP["pedido"], required=False)
    filial_col = resolve(orders, COLMAP["filial"], required=False)
    tf_col = resolve(orders, COLMAP["tipo_frete"], required=False)
    icms_col = resolve(orders, COLMAP["icms"], required=False)
    emb_col = resolve(orders, COLMAP["embalagem"], required=False)
    df_col = resolve(orders, COLMAP["desc_financ"], required=False)

    enr_cols = ["Tipo de Matéria Prima", "Linha de Produção", "Nome Curto",
                "Pedido Priorizado", "Tipo Frete", "Destino da Rota",
                "Faixa Frete (R$/t)"]
    calc_cols = [
        "Valor Venda c/ Imposto", "(-) ICMS", "(-) Custo Frete R$",
        "(-) Comissão", "(-) Embalagem", "(-) Bonificação",
        "(-) Desc. Financeiro", "(-) Custo MP R$",
        "Margem de Contribuição Nominal (MC$)",
        "Margem de Contribuição Percentual (MC%)",
    ]
    for c in enr_cols + calc_cols:
        orders[c] = None

    for i, row in orders.iterrows():
        produto = row.get(np_col)
        info = _match_info(cfg, produto) or {"nome_curto": "", "mp": "", "linhas": {}}
        mp = info.get("mp", "")
        ped = _norm_code(row.get(pedido_col)) if pedido_col else ""

        valor = to_number(row.get(valor_col))
        peso = to_number(row.get(peso_col))
        com_pct = to_number(row.get(com_col)) / 100.0  # coluna em pontos % (1,5 = 1,5%)
        bonif = to_number(row.get(bonif_col)) if bonif_col else 0.0

        # origem (planta) para frete CIF; ICMS real do arquivo (fallback 7/12)
        origem_uf = origem_uf_from_filial(row.get(filial_col)) if filial_col else UF_ORIGEM_PADRAO
        uf_cli = str(row.get(uf_col, "")).strip().upper()[:2]
        if icms_col:
            icms = to_number(row.get(icms_col))           # valor real do ERP
        else:
            aliquota = ICMS_INTERNA if uf_cli == origem_uf else ICMS_INTERESTADUAL
            icms = valor * aliquota

        # linha de envase: linhas compativeis na planta da origem
        plant_key = _plant_key_from_uf(origem_uf)
        linhas = sorted(info.get("linhas", {}).get(plant_key, set()))
        linha_txt = " / ".join(linhas)

        # frete: CIF (Emitente) usa tabela; FOB (Destinatario) = 0 (cliente paga)
        tf_raw = str(row.get(tf_col, "")).strip() if tf_col else ""
        is_fob = norm(tf_raw).startswith("destinat")
        if is_fob:
            tipo_frete, destino_rota, tarifa_t, frete = "FOB", "(cliente paga)", 0.0, 0.0
        else:
            tipo_frete = "CIF"
            if cif:
                cidade = row.get(cidade_col) if cidade_col else ""
                tarifa_t, destino_rota, frete, _st = frete_cif.resolve_frete(
                    cif, cidade, origem_uf, peso)
            else:
                tarifa_t, destino_rota, frete = 0.0, "", 0.0

        comissao = (valor - frete) * com_pct
        embalagem = to_number(row.get(emb_col)) if emb_col else 0.0     # real do ERP
        desc_fin = to_number(row.get(df_col)) if df_col else 0.0        # real do ERP
        custo_mp = custo_kg.get(mp, 0.0) * peso

        deducoes = icms + frete + comissao + embalagem + bonif + desc_fin + custo_mp
        mc = valor - deducoes
        mc_pct = (mc / valor) if valor else 0.0

        orders.at[i, "Tipo de Matéria Prima"] = mp
        orders.at[i, "Linha de Produção"] = linha_txt
        orders.at[i, "Nome Curto"] = info.get("nome_curto", "")
        orders.at[i, "Pedido Priorizado"] = "SIM" if ped in prioridade else "NÃO"
        orders.at[i, "Tipo Frete"] = tipo_frete
        orders.at[i, "Destino da Rota"] = destino_rota
        orders.at[i, "Faixa Frete (R$/t)"] = round(tarifa_t, 2)
        orders.at[i, "Valor Venda c/ Imposto"] = round(valor, 2)
        orders.at[i, "(-) ICMS"] = round(icms, 2)
        orders.at[i, "(-) Custo Frete R$"] = round(frete, 2)
        orders.at[i, "(-) Comissão"] = round(comissao, 2)
        orders.at[i, "(-) Embalagem"] = round(embalagem, 2)
        orders.at[i, "(-) Bonificação"] = round(bonif, 2)
        orders.at[i, "(-) Desc. Financeiro"] = round(desc_fin, 2)
        orders.at[i, "(-) Custo MP R$"] = round(custo_mp, 2)
        orders.at[i, "Margem de Contribuição Nominal (MC$)"] = round(mc, 2)
        orders.at[i, "Margem de Contribuição Percentual (MC%)"] = round(mc_pct, 4)

    meta = {
        "enr_cols": enr_cols, "calc_cols": calc_cols,
        "money_cols": [
            "Faixa Frete (R$/t)", "Valor Venda c/ Imposto", "(-) ICMS",
            "(-) Custo Frete R$", "(-) Comissão", "(-) Embalagem",
            "(-) Bonificação", "(-) Desc. Financeiro", "(-) Custo MP R$",
            "Margem de Contribuição Nominal (MC$)",
        ],
        "pct_cols": ["Margem de Contribuição Percentual (MC%)"],
    }
    return orders, meta


def summarize(df):
    mc_col = "Margem de Contribuição Nominal (MC$)"
    val_col = "Valor Venda c/ Imposto"
    total_venda = float(pd.to_numeric(df[val_col], errors="coerce").fillna(0).sum())
    total_mc = float(pd.to_numeric(df[mc_col], errors="coerce").fillna(0).sum())
    mc_vals = pd.to_numeric(df[mc_col], errors="coerce").fillna(0)
    negativos = int((mc_vals < 0).sum())
    return {
        "n_linhas": int(len(df)),
        "total_venda": round(total_venda, 2),
        "total_mc": round(total_mc, 2),
        "mc_medio_pct": round((total_mc / total_venda * 100) if total_venda else 0, 2),
        "negativos": negativos,
        "priorizados": int((df["Pedido Priorizado"] == "SIM").sum()),
    }
