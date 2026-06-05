# -*- coding: utf-8 -*-
"""
Resolvedor de frete pela Tabela de Rotas CIF (N1_Tabela_Rotas_CIF_Padrao).

Algoritmo:
  1. localizar a CIDADE do pedido na tabela (coluna 'Cidade Destino'),
     filtrando pela FILIAL DE ORIGEM do pedido (Itaju/SP ou Sertanopolis/PR),
     pois 141 cidades sao atendidas pelas duas origens com precos diferentes.
  2. registrar o DESTINO DA ROTA.
  3. pegar o PRECO POR TONELADA (R$/ton) na coluna da FAIXA DE PESO do pedido.
  4. Custo Frete R$ = (preco_tonelada / 1000) * Peso Total (kg)

Faixas de peso sao "Ate X" cumulativas (ex.: Ate 5.000 / Ate 8.000 / Acima de 25.000):
escolhe-se a MENOR faixa cujo limite superior cobre o peso do pedido.
"""
import re
import pandas as pd

from .columns import resolve, norm, to_number

INF = float("inf")

# ---- AJUSTE AQUI se os cabecalhos da Tabela de Rotas CIF mudarem ----
CIF_CIDADE = ["Cidade Destino", "Cidade do Cliente", "Cidade Cliente",
              "Cidade", "Municipio", "Mun"]
CIF_UF = ["UF", "Estado", "Sigla UF"]
CIF_DESTINO_ROTA = ["Destino da Rota", "Destino Rota", "Nome da Rota", "Rota"]
CIF_FILIAL_ORIGEM = ["Filial de Origem", "Filial Origem", "Origem", "Filial",
                     "Planta"]
# "auto" | "ton" | "kg"  -> unidade dos limites das faixas de peso
CIF_PESO_UNIDADE = "auto"
# --------------------------------------------------------------------


def _nums(text):
    """Extrai numeros de um texto tratando milhar BR ('25.000'->25000) e decimal ','."""
    out = []
    for tok in re.findall(r"\d[\d.,]*\d|\d", text):
        if "," in tok:                                   # decimal BR
            t = tok.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", tok):  # milhar BR: 25.000
            t = tok.replace(".", "")
        else:
            t = tok
        try:
            out.append(float(t))
        except ValueError:
            pass
    return out


def _parse_band(header):
    """Extrai (min, max) do cabecalho de uma coluna de faixa, ou None."""
    h = norm(header)
    nums = _nums(h)
    tem_ate = any(k in h for k in ("ate", "menor", "inferior", "abaixo"))
    tem_acima = any(k in h for k in ("acima", "maior", "superior", "mais de"))
    if tem_acima and nums:
        return (nums[0], INF)
    if tem_ate and nums:
        return (0.0, nums[0])
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return None


def _origem_key(value):
    """Normaliza a filial de origem para chave PR (Sertanopolis) ou SP (Itaju)."""
    s = norm(value)
    if "itaju" in s:
        return "SP"
    if "sertanopolis" in s or "matriz" in s:
        return "PR"
    m = re.search(r"\b(pr|sp)\b", s)
    return m.group(1).upper() if m else ""


def load_cif_table(config_path):
    """Localiza a aba da Tabela de Rotas CIF e monta a estrutura de consulta."""
    p = config_path.lower()
    if p.endswith(".csv") or p.endswith(".txt"):
        sheets = {"Sheet1": pd.read_csv(config_path, dtype=str, sep=None, engine="python")}
    else:
        sheets = pd.read_excel(config_path, sheet_name=None, dtype=str)

    for name, df in sheets.items():
        if df is None or df.empty:
            continue
        cidade_col = resolve(df, CIF_CIDADE, required=False)
        if cidade_col is None:
            continue
        rota_col = resolve(df, CIF_DESTINO_ROTA, required=False)
        uf_col = resolve(df, CIF_UF, required=False)
        org_col = resolve(df, CIF_FILIAL_ORIGEM, required=False)

        usados = {c for c in (cidade_col, rota_col, uf_col, org_col) if c}
        bands = []
        for col in df.columns:
            if col in usados:
                continue
            faixa = _parse_band(col)
            if faixa:
                bands.append((faixa[0], faixa[1], col))
        if not bands:
            continue  # nao e a aba CIF

        # unidade dos limites
        finitos = [hi for (_, hi, _) in bands if hi != INF] + \
                  [lo for (lo, _, _) in bands if lo > 0]
        max_fin = max(finitos) if finitos else 0
        if CIF_PESO_UNIDADE == "ton":
            fator = 1000.0
        elif CIF_PESO_UNIDADE == "kg":
            fator = 1.0
        else:
            fator = 1000.0 if max_fin and max_fin < 1000 else 1.0
        bands = [(lo * fator, (hi * fator if hi != INF else INF), col)
                 for (lo, hi, col) in bands]
        bands.sort(key=lambda b: b[1])  # por limite superior (faixas cumulativas)

        # lookup por (cidade, origem_plant) + fallback por cidade
        by_plant, by_city = {}, {}
        cidades = set()
        for _, row in df.iterrows():
            cidade = norm(row.get(cidade_col))
            if not cidade or cidade == "nan":
                continue
            plant = _origem_key(row.get(org_col)) if org_col else ""
            by_plant.setdefault((cidade, plant), row)
            by_city.setdefault(cidade, row)
            cidades.add(cidade)

        return {"by_plant": by_plant, "by_city": by_city, "cidades": cidades,
                "bands": bands, "rota_col": rota_col, "sheet": name}
    return None


def has_city(cif, cidade):
    return bool(cif) and norm(cidade) in cif["cidades"]


def resolve_frete(cif, cidade, origem_plant, peso_kg):
    """
    Retorna (tarifa_por_tonelada, destino_rota, custo_frete_rs, status, faixa_label).
    origem_plant: 'PR' (Sertanopolis) ou 'SP' (Itaju), da filial do pedido.
    status: ok | sem_tabela | cidade_nao_encontrada | faixa_nao_encontrada
    faixa_label: cabecalho da faixa de peso enquadrada (ex.: 'Até 5.000 kg') ou ''.
    """
    if not cif:
        return (0.0, "", 0.0, "sem_tabela", "")
    c = norm(cidade)
    plant = (origem_plant or "").upper()[:2]
    row = cif["by_plant"].get((c, plant))
    if row is None:
        row = cif["by_city"].get(c)
    if row is None:
        return (0.0, "", 0.0, "cidade_nao_encontrada", "")

    destino = ""
    if cif["rota_col"]:
        destino = str(row.get(cif["rota_col"], "")).strip()

    tarifa, faixa_label = None, ""
    for (lo, hi, col) in cif["bands"]:          # ordenado por limite superior
        if peso_kg >= lo and (peso_kg <= hi or hi == INF):
            tarifa = to_number(row.get(col))
            faixa_label = str(col).strip()
            break
    if tarifa is None:
        return (0.0, destino, 0.0, "faixa_nao_encontrada", "")

    custo = (tarifa / 1000.0) * peso_kg
    return (round(tarifa, 2), destino, round(custo, 2), "ok", faixa_label)
