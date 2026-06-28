# -*- coding: utf-8 -*-
"""
Persistencia DURAVEL opcional via PostgreSQL (Railway).

Objetivo: o estado (priorizacao, custos, metadados e ate os arquivos de fontes)
NAO se perder a cada novo deploy. O disco do container e efemero; um banco
Postgres (ou um Volume) sobrevive aos redeploys.

Padrao kv_store (mesmo do modulo Abastecimento):
    kv_store(colecao TEXT, id TEXT, dados JSONB, atualizado_em TIMESTAMP)

Tudo aqui e BLINDADO: se nao houver DATABASE_URL, ou se o banco falhar por
qualquer motivo, as funcoes degradam em silencio e o app continua usando o
disco normalmente (zero regressao para quem nao usa banco).
"""
import os
import json

_DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
_conn = None
_init_ok = False


def _normalize_url(url):
    # psycopg2 exige o esquema "postgresql://"; o Railway as vezes usa "postgres://"
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _get_conn():
    global _conn, _init_ok
    if not _DB_URL:
        return None
    if _conn is not None:
        try:
            with _conn.cursor() as c:
                c.execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None  # reconecta abaixo
    try:
        import psycopg2
        _conn = psycopg2.connect(_normalize_url(_DB_URL), connect_timeout=8)
        _conn.autocommit = True
        if not _init_ok:
            with _conn.cursor() as c:
                c.execute(
                    "CREATE TABLE IF NOT EXISTS kv_store ("
                    " colecao TEXT NOT NULL, id TEXT NOT NULL,"
                    " dados JSONB, atualizado_em TIMESTAMP DEFAULT now(),"
                    " PRIMARY KEY (colecao, id))")
            _init_ok = True
        return _conn
    except Exception as e:
        print("[N1] Postgres indisponivel (usando disco):", e, flush=True)
        _conn = None
        return None


def disponivel():
    """True se ha banco durável conectado."""
    return _get_conn() is not None


def kv_set(colecao, id, dados):
    conn = _get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as c:
            c.execute(
                "INSERT INTO kv_store (colecao, id, dados, atualizado_em)"
                " VALUES (%s, %s, %s, now())"
                " ON CONFLICT (colecao, id)"
                " DO UPDATE SET dados = EXCLUDED.dados, atualizado_em = now()",
                (colecao, id, json.dumps(dados, ensure_ascii=False)))
        return True
    except Exception as e:
        print("[N1] kv_set falhou:", e, flush=True)
        return False


def kv_get(colecao, id, default=None):
    conn = _get_conn()
    if not conn:
        return default
    try:
        with conn.cursor() as c:
            c.execute("SELECT dados FROM kv_store WHERE colecao=%s AND id=%s",
                      (colecao, id))
            row = c.fetchone()
            return row[0] if row else default
    except Exception:
        return default


def kv_list(colecao):
    """Lista [(id, dados), ...] de uma colecao."""
    conn = _get_conn()
    if not conn:
        return []
    try:
        with conn.cursor() as c:
            c.execute("SELECT id, dados FROM kv_store WHERE colecao=%s", (colecao,))
            return [(r[0], r[1]) for r in c.fetchall()]
    except Exception:
        return []
