# -*- coding: utf-8 -*-
"""
Eixo N1 - Modulo de Margem de Contribuicao
Flask app. Pronto para GitHub + Railway.
"""
import os
import json
import uuid
import datetime

from flask import (Flask, render_template, request, jsonify,
                   send_file, abort)
from werkzeug.utils import secure_filename

from core import processor, excel_export

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE_DIR, "data", "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

ALLOWED = {".xlsx", ".xls", ".csv", ".txt"}
MAX_MB = 25

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024


def _job_dir(job_id):
    safe = secure_filename(job_id)
    d = os.path.join(JOBS_DIR, safe)
    if not os.path.isdir(d):
        abort(404, "Job nao encontrado.")
    return d


def _ext_ok(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/upload", methods=["POST"])
def upload():
    """Etapa 1+2: recebe os arquivos, cruza e devolve os tipos de MP."""
    obrig = ("pedidos", "config", "prioridade")
    opcionais = ("cif",)
    for key in obrig:
        if key not in request.files or request.files[key].filename == "":
            return jsonify({"ok": False,
                            "error": f"Arquivo obrigatorio ausente: {key}"}), 400
    todos = obrig + opcionais
    for key in todos:
        if key in request.files and request.files[key].filename:
            if not _ext_ok(request.files[key].filename):
                return jsonify({"ok": False,
                                "error": f"Formato invalido em '{key}'. "
                                         f"Use {sorted(ALLOWED)}"}), 400

    job_id = uuid.uuid4().hex[:12]
    d = os.path.join(JOBS_DIR, job_id)
    os.makedirs(d, exist_ok=True)

    paths = {}
    orig_names = {}
    for key in todos:
        if key in request.files and request.files[key].filename:
            f = request.files[key]
            ext = os.path.splitext(f.filename)[1].lower()
            dest = os.path.join(d, f"{key}{ext}")
            f.save(dest)
            paths[key] = dest
            orig_names[key] = f.filename

    meta = {"job_id": job_id,
            "criado": datetime.datetime.now().isoformat(),
            "paths": paths, "orig_names": orig_names}
    with open(os.path.join(d, "job.json"), "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)

    try:
        result = processor.analyze(paths["pedidos"], paths["config"],
                                   paths["prioridade"], paths.get("cif"))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    result.update({"ok": True, "job_id": job_id})
    return jsonify(result)


@app.route("/generate", methods=["POST"])
def generate():
    """Etapa 3: recebe custos por saca, calcula e gera o Excel."""
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id", "")
    custos = data.get("custos", {})
    if not job_id:
        return jsonify({"ok": False, "error": "job_id ausente."}), 400

    d = _job_dir(job_id)
    with open(os.path.join(d, "job.json"), encoding="utf-8") as fp:
        meta = json.load(fp)
    paths = meta["paths"]

    # persiste os custos informados (estado em JSON, padrao do projeto)
    with open(os.path.join(d, "custos.json"), "w", encoding="utf-8") as fp:
        json.dump(custos, fp, ensure_ascii=False, indent=2)

    try:
        df, calc_meta = processor.process(
            paths["pedidos"], paths["config"], paths["prioridade"], custos,
            paths.get("cif"))
        out_path = os.path.join(d, "Analise_de_Margem.xlsx")
        excel_export.export_excel(df, calc_meta, out_path)
        resumo = processor.summarize(df)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    return jsonify({"ok": True, "job_id": job_id,
                    "download": f"/download/{job_id}",
                    "resumo": resumo})


@app.route("/download/<job_id>")
def download(job_id):
    d = _job_dir(job_id)
    out_path = os.path.join(d, "Analise_de_Margem.xlsx")
    if not os.path.isfile(out_path):
        abort(404, "Arquivo ainda nao gerado.")
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    return send_file(out_path, as_attachment=True,
                     download_name=f"Analise_de_Margem_{stamp}.xlsx")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
