# -*- coding: utf-8 -*-
"""
Normalizacao e resolucao robusta de nomes de colunas.

Resolve os problemas recorrentes de:
- acentos (matéria -> materia)
- quebras de linha dentro do cabecalho (\\n, \\r)
- espacos duplicados / espacos nas pontas
- maiusculas/minusculas
- caracteres especiais (%, R$, /, .)

Como funciona:
    Voce define, em COLMAP (processor.py), o nome LOGICO de cada campo
    e uma lista de VARIANTES aceitas de cabecalho. O resolvedor normaliza
    tudo e encontra a coluna real correspondente no DataFrame.

PONTO UNICO DE AJUSTE: se os cabecalhos dos seus arquivos forem diferentes,
edite as listas de variantes em COLMAP (no arquivo processor.py).
"""
import re
import unicodedata


def norm(s):
    """Normaliza um texto para comparacao de cabecalhos."""
    if s is None:
        return ""
    s = str(s)
    # remove acentos
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # troca quebras de linha e tabs por espaco
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # remove caracteres nao alfanumericos (mantem espaco)
    s = re.sub(r"[^0-9a-zA-Z ]", " ", s)
    # minusculo
    s = s.lower()
    # colapsa espacos
    s = " ".join(s.split())
    return s


def build_index(df):
    """Retorna {nome_normalizado: nome_real} para as colunas do DataFrame."""
    idx = {}
    for col in df.columns:
        idx.setdefault(norm(col), col)
    return idx


def resolve(df, variants, required=True, field_name=""):
    """
    Encontra a coluna real no df que corresponde a uma das variantes.

    1) tenta correspondencia exata (normalizada)
    2) tenta correspondencia por 'comeca com' / 'contem'

    Retorna o nome REAL da coluna, ou None se nao achar (e nao for obrigatorio).
    """
    idx = build_index(df)
    norm_variants = [norm(v) for v in variants]

    # 1) match exato
    for nv in norm_variants:
        if nv in idx:
            return idx[nv]

    # 2) match parcial (contains nos dois sentidos)
    for nv in norm_variants:
        for ncol, real in idx.items():
            if not nv or not ncol:
                continue
            if nv == ncol or nv in ncol or ncol in nv:
                return real

    if required:
        disponiveis = ", ".join(str(c) for c in df.columns)
        raise KeyError(
            f"Coluna obrigatoria nao encontrada: '{field_name or variants[0]}'. "
            f"Variantes testadas: {variants}. "
            f"Colunas disponiveis no arquivo: [{disponiveis}]"
        )
    return None


def to_number(value):
    """
    Converte texto/numero brasileiro em float.
    Aceita 'R$ 1.234,56', '1234,56', '12%', '1,234.56', etc.
    Retorna 0.0 para vazio/invalido.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        try:
            f = float(value)
            return 0.0 if (f != f) else f  # trata NaN
        except Exception:
            return 0.0
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none", "-"):
        return 0.0
    s = s.replace("R$", "").replace("r$", "").replace("%", "").strip()
    s = s.replace(" ", "")
    # formato BR: 1.234,56  -> tira ponto de milhar, troca virgula por ponto
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0
