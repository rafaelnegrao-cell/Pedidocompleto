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
    "financeiro":    ["Financeiro", "Status Financeiro", "Situacao Financeira",
                      "Bloqueio", "Liberacao"],
    "previsao":      ["Previsão Entrega", "Previsao Entrega", "Prev Entrega",
                      "Previsão de Embarque", "Previsao Embarque", "Data Embarque",
                      "Previsão Embarque"],
    "mix":           ["Mix Produtos", "Mix de Produtos", "Mix", "Mix Produto"],
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
def process(orders_path, config_path, priority_path, custos_saca, cif_path=None,
            custos_revenda=None, revenda_meta=None):
    orders = _read_any(orders_path)
    cfg = load_config_index(config_path)
    prioridade = load_priority_set(priority_path)
    cif = frete_cif.load_cif_table(cif_path or config_path)

    custos_revenda = custos_revenda or {}
    revenda_meta = revenda_meta or {}
    custo_kg = {mp: to_number(v) / 50.0 for mp, v in custos_saca.items()}
    custo_saca_map = {mp: to_number(v) for mp, v in custos_saca.items()}
    # revenda: custo exato POR LINHA (chave = indice) + metadados do contrato
    rev_saca_map = {str(k): to_number(v) for k, v in custos_revenda.items()}
    rev_meta_map = {str(k): (v if isinstance(v, dict) else {}) for k, v in revenda_meta.items()}

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
    mix_col = resolve(orders, COLMAP["mix"], required=False)

    enr_cols = ["Tipo de Matéria Prima", "Linha de Produção", "Nome Curto",
                "Pedido Priorizado", "Tipo Frete", "Destino da Rota",
                "Faixa Frete (R$/t)", "Faixa de Peso CIF",
                "Custo MP (R$/saca 50kg)",
                "Contrato (compra)", "Usina (compra)", "Cidade/UF (compra)"]
    calc_cols = [
        "Valor Venda c/ Imposto", "(-) ICMS", "(-) Custo Frete R$",
        "(-) Comissão", "(-) Embalagem", "(-) Bonificação",
        "(-) Desc. Financeiro", "(-) Custo MP R$",
        "Margem de Contribuição Nominal (MC$)",
        "Margem de Contribuição Percentual (MC%)",
    ]
    # 'Tipo Frete' do pedido (Emitente/Destinatario) colide com a coluna de
    # enriquecimento homonima; capturar ANTES de criar as colunas novas.
    tf_orig = orders[tf_col].copy() if tf_col else None

    for c in enr_cols + calc_cols:
        orders[c] = None

    for i, row in orders.iterrows():
        produto = row.get(np_col)
        info = _match_info(cfg, produto) or {"nome_curto": "", "mp": "", "linhas": {}}
        mp = info.get("mp", "")
        ped = _norm_code(row.get(pedido_col)) if pedido_col else ""

        # classificacao do mix: REVENDA usa custo exato de compra (por codigo),
        # nao a media de MP. Envasado (Empacotado/Especial) usa a media de MP.
        mix_raw = str(row.get(mix_col, "")) if mix_col else ""
        is_revenda = "revenda" in norm(mix_raw)
        cod = _lead_code(produto)
        if is_revenda:
            mp = "REVENDA"
            custo_saca_item = rev_saca_map.get(str(i), 0.0)   # por linha de pedido
        else:
            custo_saca_item = custo_saca_map.get(mp, 0.0)

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
        tf_raw = str(tf_orig.loc[i]) if tf_orig is not None else ""
        is_fob = norm(tf_raw).startswith("destinat")
        faixa_lbl = ""
        if is_fob:
            tipo_frete, destino_rota, tarifa_t, frete = "FOB", "(cliente paga)", 0.0, 0.0
        else:
            tipo_frete = "CIF"
            if cif:
                cidade = row.get(cidade_col) if cidade_col else ""
                tarifa_t, destino_rota, frete, _st, faixa_lbl = frete_cif.resolve_frete(
                    cif, cidade, origem_uf, peso)
            else:
                tarifa_t, destino_rota, frete = 0.0, "", 0.0

        # celula da faixa de peso CIF (+ aviso quando peso < 2.000 kg)
        if is_fob:
            faixa_cel = "FOB"
        elif faixa_lbl:
            faixa_cel = faixa_lbl
        else:
            faixa_cel = "(sem faixa)"
        if peso < 2000.0:
            faixa_cel = (faixa_cel + " · " if faixa_cel else "") + "ABAIXO DE 2.000 KG"

        comissao = (valor - frete) * com_pct
        embalagem = to_number(row.get(emb_col)) if emb_col else 0.0     # real do ERP
        desc_fin = to_number(row.get(df_col)) if df_col else 0.0        # real do ERP
        custo_mp = (custo_saca_item / 50.0) * peso

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
        orders.at[i, "Faixa de Peso CIF"] = faixa_cel
        orders.at[i, "Custo MP (R$/saca 50kg)"] = round(custo_saca_item, 2)
        _m = rev_meta_map.get(str(i), {}) if is_revenda else {}
        orders.at[i, "Usina (compra)"] = _m.get("usina", "")
        orders.at[i, "Cidade/UF (compra)"] = _m.get("cidade_uf", "")
        orders.at[i, "Contrato (compra)"] = _m.get("contrato", "")
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
            "Faixa Frete (R$/t)", "Custo MP (R$/saca 50kg)",
            "Valor Venda c/ Imposto", "(-) ICMS",
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


def carteira_resumo(orders_path, config_path, priority_path, cif_path=None):
    """
    Agrega a carteira para o painel ao vivo (MC inicial com Custo MP = 0).
    Devolve, por MP e no total: Valor, Peso e 'outras deducoes' (ICMS+Frete+
    Comissao+Embalagem+Bonificacao+Desc.Fin, independentes do custo de MP),
    alem de %CIF/FOB e %Bloqueado/Liberado por faturamento.
    O front calcula a MC ao vivo:  MC = Valor - outras - (custo_kg * Peso).
    """
    df, _ = process(orders_path, config_path, priority_path, {}, cif_path, {}, {})
    valor = pd.to_numeric(df["Valor Venda c/ Imposto"], errors="coerce").fillna(0)
    mc0 = pd.to_numeric(df["Margem de Contribuição Nominal (MC$)"], errors="coerce").fillna(0)
    outras = valor - mc0  # custo MP = 0 aqui, logo isto e a soma das demais deducoes

    peso_col = resolve(df, COLMAP["peso_total"], required=False)
    peso = df[peso_col].map(to_number) if peso_col else pd.Series([0.0] * len(df))
    np_col = resolve(df, COLMAP["nome_produto"], required=False)
    mp = df["Tipo de Matéria Prima"].fillna("").astype(str).str.strip()
    tf = df["Tipo Frete"].fillna("").astype(str).str.upper()
    mix_col = resolve(df, COLMAP["mix"], required=False)
    mixs = df[mix_col].fillna("").astype(str) if mix_col else pd.Series([""] * len(df))
    is_rev = mixs.map(lambda x: "revenda" in norm(x))
    env = ~is_rev
    fin_col = resolve(df, COLMAP["financeiro"], required=False)
    fin = df[fin_col].fillna("").astype(str) if fin_col else pd.Series([""] * len(df))
    fin_n = fin.map(norm)
    ped_col = resolve(df, COLMAP["pedido"], required=False)

    total_valor = float(valor.sum())

    # ENVASADO: por tipo de MP (exclui revenda)
    por_mp = {}
    mp_env = mp.where(env, "")
    for m in sorted(set(mp_env[env]), key=lambda x: _mp_sort_key(x) if x else (998, "")):
        sel = env & (mp == m) if m else env & (mp == "")
        if int(sel.sum()) == 0:
            continue
        key = m if m else "(sem cadastro)"
        por_mp[key] = {
            "valor": round(float(valor[sel].sum()), 2),
            "peso": round(float(peso[sel].sum()), 2),
            "outras": round(float(outras[sel].sum()), 2),
            "n_linhas": int(sel.sum()),
            "tem_mp": bool(m),
        }

    # REVENDA: cada LINHA de pedido individualmente (custo + usina por linha,
    # pois o mesmo produto pode vir de usinas diferentes com custos distintos)
    cods = df[np_col].map(_lead_code) if np_col else pd.Series([""] * len(df))
    nomes = df["Nome Curto"].fillna("").astype(str)
    prod_full = df[np_col].fillna("").astype(str) if np_col else pd.Series([""] * len(df))
    ped_series = df[ped_col].fillna("").astype(str) if ped_col else pd.Series([""] * len(df))
    cli_col = resolve(df, ["Cliente", "Nome Cliente", "Razao Social", "Razão Social"], required=False)
    cli_series = df[cli_col].fillna("").astype(str) if cli_col else pd.Series([""] * len(df))
    revenda_linhas = []
    for i in df.index[is_rev]:
        nm = str(nomes.loc[i]).strip() or str(prod_full.loc[i])
        revenda_linhas.append({
            "idx": str(i),
            "pedido": str(ped_series.loc[i]),
            "cliente": str(cli_series.loc[i]),
            "cod": str(cods.loc[i]),
            "nome": nm,
            "produto": str(prod_full.loc[i]),
            "valor": round(float(valor.loc[i]), 2),
            "peso": round(float(peso.loc[i]), 2),
            "outras": round(float(outras.loc[i]), 2),
        })

    # TOTAIS por mix de ENVASADO (consolidado ao vivo via peso por chave de MP).
    # A revenda no consolidado e calculada a partir das linhas individuais no front.
    chave = mp  # envasado -> tipo de MP
    por_mix = {}
    for mv in sorted(set(mixs)):
        if not str(mv).strip() or "revenda" in norm(mv):
            continue
        sel = (mixs == mv)
        chaves = {}
        for k in set(chave[sel]):
            kk = str(k)
            chaves[kk] = round(float(peso[sel & (chave == k)].sum()), 2)
        por_mix[mv] = {
            "valor": round(float(valor[sel].sum()), 2),
            "peso": round(float(peso[sel].sum()), 2),
            "outras": round(float(outras[sel].sum()), 2),
            "n_linhas": int(sel.sum()),
            "chaves": chaves,
        }

    cif_val = float(valor[tf == "CIF"].sum())
    fob_val = float(valor[tf == "FOB"].sum())
    bloq_val = float(valor[fin_n.str.contains("bloq")].sum())
    lib_val = float(valor[fin_n.str.contains("liber")].sum())
    pct = lambda x: round(x / total_valor * 100, 1) if total_valor else 0.0

    return {
        "ok": True,
        "total_valor": round(total_valor, 2),
        "total_peso": round(float(peso.sum()), 2),
        "total_outras": round(float(outras.sum()), 2),
        "n_linhas": int(len(df)),
        "n_pedidos": int(df[ped_col].nunique()) if ped_col else int(len(df)),
        "pct_cif": pct(cif_val), "pct_fob": pct(fob_val),
        "pct_bloqueado": pct(bloq_val), "pct_liberado": pct(lib_val),
        "por_mp": por_mp,
        "revenda_linhas": revenda_linhas,
        "por_mix": por_mix,
    }


def _sort_carteira(d, mc_asc=False):
    """Ordena: Filial -> Priorizados primeiro -> MC R$ -> Previsao de embarque.
    mc_asc=False: maior MC primeiro (principal). mc_asc=True: pior MC primeiro (atencao)."""
    if d.empty:
        return d
    d = d.copy()
    fil_col = resolve(d, COLMAP["filial"], required=False)
    prev_col = resolve(d, COLMAP["previsao"], required=False)
    d["__fil"] = d[fil_col].astype(str) if fil_col else ""
    d["__prio"] = (d["Pedido Priorizado"].astype(str).str.upper() == "SIM").map({True: 0, False: 1})
    d["__mc"] = pd.to_numeric(d["Margem de Contribuição Nominal (MC$)"], errors="coerce").fillna(0)
    d["__prev"] = pd.to_datetime(d[prev_col], errors="coerce") if prev_col else pd.NaT
    d = d.sort_values(by=["__fil", "__prio", "__mc", "__prev"],
                      ascending=[True, True, mc_asc, True], na_position="last")
    return d.drop(columns=["__fil", "__prio", "__mc", "__prev"])


def _partition_env(env):
    """Separa pedidos ENVASADOS em principal (priorizados + limpos) e atencao."""
    if env.empty:
        return env, env
    prio = env["Pedido Priorizado"].astype(str).str.upper() == "SIM"
    mc = pd.to_numeric(env["Margem de Contribuição Nominal (MC$)"], errors="coerce").fillna(0)
    tf = env["Tipo Frete"].astype(str).str.upper()
    destino = env["Destino da Rota"].fillna("").astype(str).str.strip()
    sem_rota = (tf == "CIF") & (destino == "")
    neg = mc < 0
    fin_col = resolve(env, COLMAP["financeiro"], required=False)
    bloq = env[fin_col].map(norm).str.contains("bloq", na=False) if fin_col else pd.Series(False, index=env.index)
    excecao = (~prio) & (sem_rota | neg | bloq)
    return _sort_carteira(env[~excecao], mc_asc=False), _sort_carteira(env[excecao], mc_asc=True)


def _fob_sheet(df):
    """Aba FOB enxuta: data agendada de retirada (manual) + pedido, cliente,
    filial, vendedor, data do pedido, produto, valor e margem de contribuicao."""
    fob = df[df["Tipo Frete"].astype(str).str.upper() == "FOB"].copy()
    if fob.empty:
        return fob
    fil_col = resolve(fob, COLMAP["filial"], required=False)
    prev_col = resolve(fob, COLMAP["previsao"], required=False)
    fob["__fil"] = fob[fil_col].astype(str) if fil_col else ""
    fob["__prev"] = pd.to_datetime(fob[prev_col], errors="coerce") if prev_col else pd.NaT
    fob = fob.sort_values(by=["__fil", "__prev"], ascending=[True, True],
                          na_position="last").drop(columns=["__fil", "__prev"])

    ped_col = resolve(fob, COLMAP["pedido"], required=False)
    cli_col = resolve(fob, ["Cliente", "Nome Cliente", "Razao Social", "Razão Social"], required=False)
    vend_col = resolve(fob, ["Vendedor", "Representante", "Rep", "Vendedor/Rep"], required=False)
    data_col = resolve(fob, ["Emissão Pedido", "Emissao Pedido", "Data Pedido",
                             "Data do Pedido", "Data"], required=False)
    prod_col = resolve(fob, COLMAP["nome_produto"], required=False)
    desejadas = [ped_col, cli_col, fil_col, vend_col, data_col, prod_col,
                 "Valor Venda c/ Imposto",
                 "Margem de Contribuição Nominal (MC$)",
                 "Margem de Contribuição Percentual (MC%)"]
    cols = [c for c in desejadas if c and c in fob.columns]
    slim = fob[cols].copy()
    if data_col and data_col in slim.columns:
        dt = pd.to_datetime(slim[data_col], errors="coerce")
        slim[data_col] = dt.dt.strftime("%d/%m/%Y").where(dt.notna(), slim[data_col].astype(str))
    slim.insert(0, "Data Agendada Retirada", "")
    return slim


def _consolidado(df):
    """Resumo por mix de produto: volume (t), faturamento, MC R$ e MC%."""
    mix_col = resolve(df, COLMAP["mix"], required=False)
    peso_col = resolve(df, COLMAP["peso_total"], required=False)
    mixs = df[mix_col].fillna("").astype(str) if mix_col else pd.Series(["(sem mix)"] * len(df))
    peso = df[peso_col].map(to_number) if peso_col else pd.Series([0.0] * len(df))
    valor = pd.to_numeric(df["Valor Venda c/ Imposto"], errors="coerce").fillna(0)
    mc = pd.to_numeric(df["Margem de Contribuição Nominal (MC$)"], errors="coerce").fillna(0)
    rows = []
    for mv in sorted(set(mixs[mixs.str.strip() != ""])):
        sel = mixs == mv
        v = float(valor[sel].sum()); m = float(mc[sel].sum())
        rows.append({"Mix de Produto": mv, "Volume (t)": round(float(peso[sel].sum()) / 1000, 2),
                     "Faturamento (R$)": round(v, 2), "MC (R$)": round(m, 2),
                     "MC (%)": round(m / v, 4) if v else 0.0})
    v = float(valor.sum()); m = float(mc.sum())
    rows.append({"Mix de Produto": "TOTAL GERAL", "Volume (t)": round(float(peso.sum()) / 1000, 2),
                 "Faturamento (R$)": round(v, 2), "MC (R$)": round(m, 2),
                 "MC (%)": round(m / v, 4) if v else 0.0})
    return pd.DataFrame(rows, columns=["Mix de Produto", "Volume (t)", "Faturamento (R$)", "MC (R$)", "MC (%)"])


def build_outputs(df):
    """
    Gera os DataFrames das abas:
      - main : ENVASADO (Empacotado/Especial) limpo + priorizados
      - exc  : ENVASADO em atencao (sem rota / MC neg / bloqueado, nao priorizado)
      - rev  : REVENDA (custo exato de compra)
      - fob  : todos os pedidos FOB (+ coluna manual de retirada)
      - consol: resumo por mix de produto (volume e margem) + total
    """
    mix_col = resolve(df, COLMAP["mix"], required=False)
    mixs = df[mix_col].fillna("").astype(str) if mix_col else pd.Series([""] * len(df))
    is_rev = mixs.map(lambda x: "revenda" in norm(x))
    env, rev = df[~is_rev], df[is_rev]
    df_main, df_exc = _partition_env(env)
    df_rev = _sort_carteira(rev, mc_asc=False)
    df_fob = _fob_sheet(df)
    df_consol = _consolidado(df)
    return df_main, df_exc, df_rev, df_fob, df_consol


# compatibilidade retroativa
def partition_and_sort(df):
    """Particiona a carteira COMPLETA (envasado + revenda) em principal /
    atencao / FOB. Revenda entra na principal com seu custo exato ja aplicado."""
    prio = df["Pedido Priorizado"].astype(str).str.upper() == "SIM"
    mc = pd.to_numeric(df["Margem de Contribuição Nominal (MC$)"], errors="coerce").fillna(0)
    tf = df["Tipo Frete"].astype(str).str.upper()
    destino = df["Destino da Rota"].fillna("").astype(str).str.strip()
    sem_rota = (tf == "CIF") & (destino == "")
    neg = mc < 0
    fin_col = resolve(df, COLMAP["financeiro"], required=False)
    bloq = df[fin_col].map(norm).str.contains("bloq", na=False) if fin_col else pd.Series(False, index=df.index)
    excecao = (~prio) & (sem_rota | neg | bloq)
    df_full = _sort_carteira(df, mc_asc=False)              # todos os pedidos
    df_main = _sort_carteira(df[~excecao], mc_asc=False)    # elegiveis
    df_exc = _sort_carteira(df[excecao], mc_asc=True)        # atencao
    df_fob = _fob_sheet(df)
    return df_full, df_main, df_exc, df_fob


def load_contratos(path):
    """Le a aba 'CADASTRO DE COMPRAS' do controle de compras e devolve a lista
    de contratos selecionaveis (cada linha = uma opcao), com custo NET por saca."""
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    except Exception:
        return []
    target = None
    for name, d in sheets.items():
        if "cadastro" in norm(name) and "compra" in norm(name):
            target = d; break
    if target is None:
        for name, d in sheets.items():
            if d is not None and resolve(d, ["Nº Contrato", "No Contrato",
                    "Numero Contrato", "Contrato"], required=False):
                target = d; break
    if target is None or target.empty:
        return []
    df = target.dropna(how="all")
    c_contr = resolve(df, ["Nº Contrato", "No Contrato", "Numero Contrato", "N Contrato", "Contrato"], required=False)
    c_usina = resolve(df, ["Fornecedor (Usina / Destilaria)", "Fornecedor", "Usina", "Destilaria"], required=False)
    c_cuf = resolve(df, ["Cidade/UF", "Cidade UF", "Cidade", "Municipio/UF"], required=False)
    c_mp = resolve(df, ["Matéria Prima", "Materia Prima", "MP"], required=False)
    c_tipo = resolve(df, ["Tipo Açúcar", "Tipo Acucar", "Tipo de Açúcar"], required=False)
    c_emb = resolve(df, ["Embalagem"], required=False)
    c_planta = resolve(df, ["Planta Origem", "Planta", "Origem"], required=False)
    c_net = resolve(df, ["Preço Net R$/saca", "Preco Net R$/saca", "Net R$/saca",
                         "Preço Net Saca", "Preco Net Saca"], required=False)
    c_saca = resolve(df, ["Preço R$/saca", "Preco R$/saca", "R$/saca", "Preço Saca"], required=False)
    c_sal_sc = resolve(df, ["Saldo (sacas) ▶ fórmula", "Saldo (sacas)", "Saldo sacas", "Saldo Sacas"], required=False)
    c_sal_kg = resolve(df, ["Saldo (kg) ▶ fórmula", "Saldo (kg)", "Saldo kg"], required=False)
    c_status = resolve(df, ["Status ▶ automático", "Status", "Situacao", "Situação"], required=False)
    out = []
    for k, (_, row) in enumerate(df.iterrows()):
        contrato = str(row.get(c_contr, "")).strip() if c_contr else ""
        if not contrato or contrato.lower() == "nan":
            continue
        net = to_number(row.get(c_net)) if c_net else 0.0
        if not net and c_saca:
            net = to_number(row.get(c_saca))
        sal_sc = to_number(row.get(c_sal_sc)) if c_sal_sc else 0.0
        sal_kg = to_number(row.get(c_sal_kg)) if c_sal_kg else 0.0
        out.append({
            "id": str(k),
            "contrato": contrato,
            "usina": (str(row.get(c_usina, "")).strip() if c_usina else ""),
            "cidade_uf": (str(row.get(c_cuf, "")).strip() if c_cuf else ""),
            "mp": (str(row.get(c_mp, "")).strip() if c_mp else ""),
            "tipo": (str(row.get(c_tipo, "")).strip() if c_tipo else ""),
            "embalagem": (str(row.get(c_emb, "")).strip() if c_emb else ""),
            "planta": (str(row.get(c_planta, "")).strip() if c_planta else ""),
            "custo_saca": round(net, 2),
            "saldo_sacas": round(sal_sc, 0),
            "saldo_ton": round(sal_kg / 1000.0, 1) if sal_kg else round(sal_sc * 50 / 1000.0, 1),
            "status": (str(row.get(c_status, "")).strip() if c_status else ""),
        })
    return out


def _revenda_sheet(df):
    """Aba dedicada de revenda: pedido, cliente, filial, vendedor, produto,
    contrato, usina, cidade/UF, custo NET por saca, valor e MC."""
    mix_col = resolve(df, COLMAP["mix"], required=False)
    mixs = df[mix_col].fillna("").astype(str) if mix_col else pd.Series([""] * len(df))
    rev = df[mixs.map(lambda x: "revenda" in norm(x))].copy()
    if rev.empty:
        return rev
    ped = resolve(rev, COLMAP["pedido"], required=False)
    cli = resolve(rev, ["Cliente", "Nome Cliente", "Razao Social", "Razão Social"], required=False)
    fil = resolve(rev, COLMAP["filial"], required=False)
    vend = resolve(rev, ["Vendedor", "Representante", "Rep"], required=False)
    prod = resolve(rev, COLMAP["nome_produto"], required=False)
    if fil:
        rev = rev.sort_values(by=[c for c in [fil, ped] if c], na_position="last")
    desejadas = [ped, cli, fil, vend, prod,
                 "Contrato (compra)", "Usina (compra)", "Cidade/UF (compra)",
                 "Custo MP (R$/saca 50kg)", "Valor Venda c/ Imposto",
                 "Margem de Contribuição Nominal (MC$)",
                 "Margem de Contribuição Percentual (MC%)"]
    cols = [c for c in desejadas if c and c in rev.columns]
    return rev[cols].copy()


def build_outputs_v2(df):
    """Retorna (carteira_completa, elegiveis, atencao, fob, revenda)."""
    df_full, df_main, df_exc, df_fob = partition_and_sort(df)
    df_rev = _revenda_sheet(df)
    return df_full, df_main, df_exc, df_fob, df_rev
