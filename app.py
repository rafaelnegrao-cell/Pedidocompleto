# -*- coding: utf-8 -*-
"""
Eixo N1 - Modulo de Margem de Contribuicao
Fluxo:
  1) Fontes de dados (Config, CIF, Priorizados) -> recebidas, SALVAS e FIXAS
  2) Custos de MP (tipos vindos do Config) -> SALVOS
  3) Pedido a Faturar -> upload so apos custos -> gera a planilha
Persiste sempre os ultimos arquivos importados e os ultimos custos de MP.
Pronto para GitHub + Railway.
"""
import os
import json
import uuid
import glob
import datetime

from flask import Flask, render_template, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

from core import processor, excel_export

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "data", "state")
SRC_DIR = os.path.join(STATE_DIR, "sources")
OUT_DIR = os.path.join(STATE_DIR, "out")
os.makedirs(SRC_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

META_PATH = os.path.join(STATE_DIR, "meta.json")
CUSTOS_PATH = os.path.join(STATE_DIR, "custos.json")
SRC_KEYS = ("config", "cif", "prioridade")

ALLOWED = {".xlsx", ".xls", ".csv", ".txt"}
MAX_MB = 30

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024


def _ext_ok(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED


def _saved_path(key):
    hits = glob.glob(os.path.join(SRC_DIR, key + ".*"))
    return hits[0] if hits else None


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def _state():
    """Estado persistido atual: fontes salvas, custos e tipos de MP."""
    meta = _load_json(META_PATH, {})
    custos = _load_json(CUSTOS_PATH, {})
    sources = {}
    for k in SRC_KEYS:
        p = _saved_path(k)
        sources[k] = ({"name": meta.get(k, {}).get("name", os.path.basename(p)),
                       "saved": meta.get(k, {}).get("saved", "")} if p else None)

    mp_types, mp_err = [], None
    cfg_path = _saved_path("config")
    if cfg_path:
        try:
            mp_types = processor.mp_types_from_config(cfg_path)
        except Exception as e:
            mp_err = str(e)

    meta_c = _load_json(META_PATH, {}).get("carteira")
    ped_path = os.path.join(OUT_DIR, "pedidos.xlsx")
    ped_alt = glob.glob(os.path.join(OUT_DIR, "pedidos.*"))
    carteira = meta_c if (ped_alt) else None

    return {
        "sources": sources,
        "custos": custos,
        "mp_types": mp_types,
        "mp_err": mp_err,
        "carteira": carteira,
        "fontes_ok": all(sources[k] for k in SRC_KEYS),
        "custos_ok": bool(custos) and bool(mp_types),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/state")
def state():
    return jsonify(_state())


@app.route("/sources", methods=["POST"])
def sources():
    """Etapa 1: recebe, salva e fixa as fontes (config, cif, prioridade)."""
    salvos = []
    for key in SRC_KEYS:
        if key in request.files and request.files[key].filename:
            f = request.files[key]
            if not _ext_ok(f.filename):
                return jsonify({"ok": False,
                                "error": f"Formato invalido em '{key}'."}), 400
            for old in glob.glob(os.path.join(SRC_DIR, key + ".*")):
                os.remove(old)
            ext = os.path.splitext(f.filename)[1].lower()
            f.save(os.path.join(SRC_DIR, f"{key}{ext}"))
            meta = _load_json(META_PATH, {})
            meta[key] = {"name": f.filename,
                         "saved": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")}
            _save_json(META_PATH, meta)
            salvos.append(key)

    st = _state()
    if not st["sources"].get("config"):
        return jsonify({"ok": False,
                        "error": "Config (N1_Config_Producao_Compilado) e obrigatorio."}), 400
    st["ok"] = True
    st["salvos"] = salvos
    return jsonify(st)


@app.route("/custos", methods=["POST"])
def custos():
    """Etapa 2: salva os custos de MP por saca (50kg)."""
    data = request.get_json(force=True, silent=True) or {}
    custos_in = data.get("custos", {})
    _save_json(CUSTOS_PATH, custos_in)
    return jsonify({"ok": True, "custos": custos_in})


def _saved_pedidos():
    hits = glob.glob(os.path.join(OUT_DIR, "pedidos.*"))
    return hits[0] if hits else None


@app.route("/carteira", methods=["POST", "GET"])
def carteira():
    """Recebe (ou recarrega) a carteira 'A faturar', salva e devolve o resumo
    para o painel ao vivo (indicadores + volume por MP, MC inicial em 0)."""
    cfg_path = _saved_path("config")
    cif_path = _saved_path("cif")
    pri_path = _saved_path("prioridade")
    if not (cfg_path and cif_path and pri_path):
        return jsonify({"ok": False,
                        "error": "Salve as Fontes (Config, CIF, Priorizados) na Etapa 1 primeiro."}), 400

    if request.method == "POST":
        if "pedidos" not in request.files or request.files["pedidos"].filename == "":
            return jsonify({"ok": False, "error": "Envie o arquivo de pedidos."}), 400
        f = request.files["pedidos"]
        if not _ext_ok(f.filename):
            return jsonify({"ok": False, "error": "Formato invalido."}), 400
        for old in glob.glob(os.path.join(OUT_DIR, "pedidos.*")):
            os.remove(old)
        ext = os.path.splitext(f.filename)[1].lower()
        f.save(os.path.join(OUT_DIR, f"pedidos{ext}"))
        meta = _load_json(META_PATH, {})
        meta["carteira"] = {"name": f.filename,
                            "saved": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")}
        _save_json(META_PATH, meta)

    ped_path = _saved_pedidos()
    if not ped_path:
        return jsonify({"ok": False, "error": "Nenhuma carteira salva."}), 404

    try:
        resumo = processor.carteira_resumo(ped_path, cfg_path, pri_path, cif_path)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    resumo["custos"] = _load_json(CUSTOS_PATH, {})
    return jsonify(resumo)


@app.route("/generate", methods=["POST"])
def generate():
    """Gera a Planilha de Pedido Completo a partir da carteira salva + custos."""
    data = request.get_json(force=True, silent=True) or {}
    custos_in = data.get("custos", {})

    cfg_path = _saved_path("config")
    cif_path = _saved_path("cif")
    pri_path = _saved_path("prioridade")
    ped_path = _saved_pedidos()
    if not (cfg_path and cif_path and pri_path):
        return jsonify({"ok": False, "error": "Fontes incompletas (Etapa 1)."}), 400
    if not ped_path:
        return jsonify({"ok": False, "error": "Carregue a carteira na Etapa 2."}), 400
    if not custos_in:
        custos_in = _load_json(CUSTOS_PATH, {})
    if not custos_in:
        return jsonify({"ok": False, "error": "Informe os custos de MP."}), 400

    _save_json(CUSTOS_PATH, custos_in)  # persiste os ultimos custos
    try:
        df, meta = processor.process(ped_path, cfg_path, pri_path, custos_in, cif_path)
        df_main, df_exc = processor.partition_and_sort(df)
        out_path = os.path.join(OUT_DIR, "Analise_de_Margem.xlsx")
        excel_export.export_excel(df_main, df_exc, meta, out_path)
        resumo = processor.summarize(df)
        diag = processor.diagnostics(df)
        diag["n_excecoes"] = int(len(df_exc))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    job = uuid.uuid4().hex[:8]
    return jsonify({"ok": True, "download": f"/download/{job}",
                    "resumo": resumo, "diag": diag})


@app.route("/download/<job_id>")
def download(job_id):
    out_path = os.path.join(OUT_DIR, "Analise_de_Margem.xlsx")
    if not os.path.isfile(out_path):
        abort(404, "Arquivo ainda nao gerado.")
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    return send_file(out_path, as_attachment=True,
                     download_name=f"Analise_de_Margem_{stamp}.xlsx")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
