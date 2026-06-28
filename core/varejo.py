# -*- coding: utf-8 -*-
"""
Blueprint da Tabela Varejo, integrada ao modulo Pedido Completo.

Isolada do nucleo de Pedido Completo:
  - rotas sob o prefixo /varejo
  - persistencia em arquivos de NOME PROPRIO dentro do mesmo diretorio de
    estado (volume do Railway): 'varejo_rotas_cache.json' e 'varejo_tabelas.json'.
    Nao toca em sources/, custos.json, meta.json, etc.
"""
import os
import json
import tempfile

import pandas as pd
from flask import (
    Blueprint, render_template, current_app, request, jsonify
)

from core import store

bp = Blueprint("varejo", __name__, url_prefix="/varejo")


def _load_dur(path, default):
    """Le do disco; se vazio (pos-redeploy) e houver banco, restaura de la."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    val = store.kv_get("state", os.path.basename(path), None)
    if val is not None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(val, f, ensure_ascii=False)
        except Exception:
            pass
        return val
    return default


def _save_dur(path, data):
    """Grava no disco e espelha no banco durável (no-op sem banco)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    store.kv_set("state", os.path.basename(path), data)


def _vdir():
    """Diretorio de estado da Varejo (mesmo volume persistente do app)."""
    d = current_app.config.get("VAREJO_DIR") or os.path.join(
        current_app.root_path, "data", "state")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_path():
    return os.path.join(_vdir(), "varejo_rotas_cache.json")


def _hist_path():
    return os.path.join(_vdir(), "varejo_tabelas.json")


# ── leitura de fretes (aba "Resumo por Rota"); UF derivado do codigo Tabela CIF ──
def _rotas_from_resumo(path_rotas):
    try:
        df = pd.read_excel(path_rotas, sheet_name="Resumo por Rota", header=2)
    except Exception:
        return None

    def parse_filial(s):
        return "Itaju/SP" if "Itaju" in str(s) else "Sertanopolis/PR"

    rotas = []
    for _, row in df.iterrows():
        cod = str(row.iloc[0]).strip()
        if not cod.startswith("ROTA"):
            continue
        filial = parse_filial(row.iloc[2])

        tabela_cif = ""
        try:
            v = row.iloc[11]
            if pd.notna(v) and str(v).strip() not in ("", "nan", "None"):
                tabela_cif = str(v).strip()
        except (IndexError, KeyError):
            pass

        if tabela_cif and "-" in tabela_cif:
            estado = tabela_cif.split("-")[0]
        else:
            try:
                n = int(cod.replace("ROTA", "").strip())
                if n < 200 or n == 51:
                    estado = "PR"
                elif n < 300:
                    estado = "SC"
                elif n < 400:
                    estado = "RS"
                elif n < 500:
                    estado = "SP"
                elif n == 500:
                    estado = "RJ"
                else:
                    estado = ""
            except Exception:
                estado = ""

        def _int(col):
            try:
                return int(row.iloc[col]) if pd.notna(row.iloc[col]) else 0
            except Exception:
                return 0

        rotas.append({
            "cod": cod,
            "destino":    str(row.iloc[1]).strip(),
            "filial":     filial,
            "estado":     estado,
            "tabela_cif": tabela_cif,
            "f2100":  _int(6), "f5000":  _int(7), "f8000":  _int(8),
            "f13100": _int(9), "f27000": _int(10),
        })
    return rotas if rotas else None


def _carregar_rotas_cif():
    rotas = _load_dur(_cache_path(), None)
    return rotas if rotas else None


@bp.route("/")
def index():
    rotas_cif = _carregar_rotas_cif()
    return render_template(
        "varejo.html",
        active="varejo",
        rotas_cif_json=json.dumps(rotas_cif, ensure_ascii=False) if rotas_cif else None,
        contratos_mp_json="[]",
        faturados_pre_json="null",
        faturados_nome=None,
        cidades_cif_json="[]",
    )


@bp.route("/upload_rotas", methods=["POST"])
def upload_rotas():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "erro": "Arquivo nao enviado"}), 400
    try:
        suffix = os.path.splitext(f.filename)[1] or ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name
        rotas = _rotas_from_resumo(tmp_path)
        os.unlink(tmp_path)
        if not rotas:
            return jsonify({"ok": False, "erro": "Nenhuma rota encontrada no arquivo"}), 400
        with open(_cache_path(), "w", encoding="utf-8") as fc:
            json.dump(rotas, fc, ensure_ascii=False)
        store.kv_set("state", os.path.basename(_cache_path()), rotas)
        n_cif = sum(1 for r in rotas if r.get("tabela_cif"))
        return jsonify({"ok": True, "rotas": len(rotas), "com_cif": n_cif})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@bp.route("/api/publicar-tabela", methods=["POST"])
def publicar_tabela():
    try:
        versao = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "erro": "JSON invalido"}), 400
    hist_path = _hist_path()
    hist = _load_dur(hist_path, []) or []
    hist.append(versao)
    try:
        _save_dur(hist_path, hist)
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500
    return jsonify({"ok": True, "id": versao.get("id"), "total": len(hist)})


@bp.route("/api/tabelas-publicadas", methods=["GET"])
def tabelas_publicadas():
    return jsonify(_load_dur(_hist_path(), []) or [])
