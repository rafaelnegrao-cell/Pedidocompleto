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
from core import store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _dir_gravavel(p):
    try:
        os.makedirs(p, exist_ok=True)
        t = os.path.join(p, ".w_test")
        with open(t, "w") as fp:
            fp.write("ok")
        os.remove(t)
        return True
    except Exception:
        return False


def _resolve_state_dir():
    """Define onde guardar o estado e se esse local SOBREVIVE a um redeploy.
    Persistente quando: (a) ha banco Postgres (DATABASE_URL), ou
    (b) ha um Volume do Railway (RAILWAY_VOLUME_MOUNT_PATH) / DATA_DIR."""
    for env in ("DATA_DIR", "RAILWAY_VOLUME_MOUNT_PATH"):
        p = os.environ.get(env)
        if p:
            d = os.path.join(p, "n1_state")
            if _dir_gravavel(d):
                return d, True
    return os.path.join(BASE_DIR, "data", "state"), False


STATE_DIR, _VOLUME_OK = _resolve_state_dir()
# durável = ha banco OU volume. Banco sozinho ja basta para nao perder nada.
STATE_PERSISTENTE = bool(store.disponivel() or _VOLUME_OK)
SRC_DIR = os.path.join(STATE_DIR, "sources")
OUT_DIR = os.path.join(STATE_DIR, "out")
os.makedirs(SRC_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
print(f"[N1] STATE_DIR={STATE_DIR} | volume={_VOLUME_OK} | banco={store.disponivel()} "
      f"| persistente={STATE_PERSISTENTE}", flush=True)

META_PATH = os.path.join(STATE_DIR, "meta.json")
CUSTOS_PATH = os.path.join(STATE_DIR, "custos.json")
CUSTOS_REV_PATH = os.path.join(STATE_DIR, "custos_revenda.json")
REVENDA_META_PATH = os.path.join(STATE_DIR, "revenda_meta.json")
PRIORIZACAO_PATH = os.path.join(STATE_DIR, "priorizacao.json")
SRC_KEYS = ("config", "cif")
OPT_SRC_KEYS = ("compras",)          # controle de compras (opcional, p/ revenda)
ALL_SRC_KEYS = SRC_KEYS + OPT_SRC_KEYS

ALLOWED = {".xlsx", ".xls", ".csv", ".txt"}
MAX_MB = 30

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

# --- Integracao Tabela Varejo (aditivo; persistencia separada no mesmo volume) ---
from core import varejo as varejo_module
app.config["VAREJO_DIR"] = STATE_DIR
app.register_blueprint(varejo_module.bp)


def _ext_ok(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED


def _saved_path(key):
    hits = glob.glob(os.path.join(SRC_DIR, key + ".*"))
    return hits[0] if hits else None


def _load_json(path, default):
    # 1) disco (rapido e fonte da verdade quando existe)
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        pass
    # 2) container novo (pos-redeploy) sem volume: tenta o banco
    val = store.kv_get("state", os.path.basename(path), None)
    if val is not None:
        try:  # restaura no disco local p/ leituras seguintes
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(val, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return val
    return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    store.kv_set("state", os.path.basename(path), data)  # espelho durável (no-op sem banco)


def _state():
    """Estado persistido atual: fontes salvas, custos e tipos de MP."""
    meta = _load_json(META_PATH, {})
    custos = _load_json(CUSTOS_PATH, {})
    sources = {}
    for k in ALL_SRC_KEYS:
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

    contratos = []
    compras_path = _saved_path("compras")
    if compras_path:
        try:
            contratos = processor.load_contratos(compras_path)
        except Exception:
            contratos = []

    meta_c = _load_json(META_PATH, {}).get("carteira")
    ped_alt = glob.glob(os.path.join(OUT_DIR, "pedidos.*"))
    carteira = meta_c if (ped_alt) else None

    gerado = meta.get("gerado") if os.path.isfile(os.path.join(OUT_DIR, "Analise_de_Margem.xlsx")) else None
    return {
        "sources": sources,
        "gerado": gerado,
        "custos": custos,
        "custos_revenda": _load_json(CUSTOS_REV_PATH, {}),
        "revenda_meta": _load_json(REVENDA_META_PATH, {}),
        "contratos": contratos,
        "mp_types": mp_types,
        "mp_err": mp_err,
        "carteira": carteira,
        "fontes_ok": all(sources[k] for k in SRC_KEYS),
        "custos_ok": bool(custos) and bool(mp_types),
        "persistente": STATE_PERSISTENTE,
        "armazenamento": ("Banco de dados" if store.disponivel()
                          else ("Volume" if _VOLUME_OK else "Efêmero (sem volume/banco)")),
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
    for key in ALL_SRC_KEYS:
        if key in request.files and request.files[key].filename:
            f = request.files[key]
            if not _ext_ok(f.filename):
                return jsonify({"ok": False,
                                "error": f"Formato invalido em '{key}'."}), 400
            for old in glob.glob(os.path.join(SRC_DIR, key + ".*")):
                os.remove(old)
            ext = os.path.splitext(f.filename)[1].lower()
            disk_path = os.path.join(SRC_DIR, f"{key}{ext}")
            f.save(disk_path)
            _mirror_file_to_db(key, disk_path)
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
    """Auto-save dos custos digitados: MP por saca, custo e usina de revenda."""
    data = request.get_json(force=True, silent=True) or {}
    if "custos" in data:
        _save_json(CUSTOS_PATH, data.get("custos") or {})
    if "custos_revenda" in data:
        _save_json(CUSTOS_REV_PATH, data.get("custos_revenda") or {})
    if "revenda_meta" in data:
        _save_json(REVENDA_META_PATH, data.get("revenda_meta") or {})
    return jsonify({"ok": True})


def _saved_pedidos():
    hits = glob.glob(os.path.join(OUT_DIR, "pedidos.*"))
    return hits[0] if hits else None


def _mirror_file_to_db(colecao_id, disk_path):
    """Espelha um arquivo (fonte/carteira) no banco em base64 (no-op sem banco)."""
    try:
        import base64
        with open(disk_path, "rb") as fp:
            b64 = base64.b64encode(fp.read()).decode("ascii")
        store.kv_set("arquivos", colecao_id,
                     {"name": os.path.basename(disk_path), "b64": b64})
    except Exception as e:
        print("[N1] espelho de arquivo falhou:", colecao_id, e, flush=True)


def _rehydrate_from_db():
    """Pos-redeploy sem volume: restaura fontes e carteira do banco para o disco."""
    if not store.disponivel():
        return
    alvos = list(ALL_SRC_KEYS) + ["pedidos"]
    for key in alvos:
        destino_dir = OUT_DIR if key == "pedidos" else SRC_DIR
        if glob.glob(os.path.join(destino_dir, key + ".*")):
            continue  # ja existe no disco
        rec = store.kv_get("arquivos", key, None)
        if rec and rec.get("b64"):
            try:
                import base64
                ext = os.path.splitext(rec.get("name", key))[1].lower() or ".xlsx"
                with open(os.path.join(destino_dir, f"{key}{ext}"), "wb") as fp:
                    fp.write(base64.b64decode(rec["b64"]))
                print(f"[N1] '{key}' restaurado do banco.", flush=True)
            except Exception as e:
                print("[N1] reidratacao falhou:", key, e, flush=True)


@app.route("/carteira", methods=["POST", "GET"])
def carteira():
    """Recebe (ou recarrega) a carteira 'A faturar', salva e devolve o resumo
    para o painel ao vivo (indicadores + volume por MP, MC inicial em 0)."""
    cfg_path = _saved_path("config")
    cif_path = _saved_path("cif")
    pri_path = _saved_path("prioridade")
    if not (cfg_path and cif_path):
        return jsonify({"ok": False,
                        "error": "Salve as Fontes (Config e CIF) na Etapa 1 primeiro."}), 400

    if request.method == "POST":
        if "pedidos" not in request.files or request.files["pedidos"].filename == "":
            return jsonify({"ok": False, "error": "Envie o arquivo de pedidos."}), 400
        f = request.files["pedidos"]
        if not _ext_ok(f.filename):
            return jsonify({"ok": False, "error": "Formato invalido."}), 400
        for old in glob.glob(os.path.join(OUT_DIR, "pedidos.*")):
            os.remove(old)
        ext = os.path.splitext(f.filename)[1].lower()
        disk_path = os.path.join(OUT_DIR, f"pedidos{ext}")
        f.save(disk_path)
        _mirror_file_to_db("pedidos", disk_path)
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
    resumo["custos_revenda"] = _load_json(CUSTOS_REV_PATH, {})
    resumo["revenda_meta"] = _load_json(REVENDA_META_PATH, {})
    cp = _saved_path("compras")
    resumo["contratos"] = processor.load_contratos(cp) if cp else []
    return jsonify(resumo)


@app.route("/generate", methods=["POST"])
def generate():
    """Gera a Planilha de Pedido Completo a partir da carteira salva + custos."""
    data = request.get_json(force=True, silent=True) or {}
    custos_in = data.get("custos", {})
    custos_rev_in = data.get("custos_revenda", {})
    revenda_meta_in = data.get("revenda_meta", {})

    cfg_path = _saved_path("config")
    cif_path = _saved_path("cif")
    pri_path = _saved_path("prioridade")
    ped_path = _saved_pedidos()
    if not (cfg_path and cif_path):
        return jsonify({"ok": False, "error": "Fontes incompletas (Config e CIF) na Etapa 1."}), 400
    if not ped_path:
        return jsonify({"ok": False, "error": "Carregue a carteira na Etapa 2."}), 400
    if not custos_in:
        custos_in = _load_json(CUSTOS_PATH, {})
    if not custos_rev_in:
        custos_rev_in = _load_json(CUSTOS_REV_PATH, {})
    if not revenda_meta_in:
        revenda_meta_in = _load_json(REVENDA_META_PATH, {})
    if not custos_in and not custos_rev_in:
        return jsonify({"ok": False, "error": "Informe os custos de MP e/ou de revenda."}), 400

    _save_json(CUSTOS_PATH, custos_in)
    _save_json(CUSTOS_REV_PATH, custos_rev_in)
    _save_json(REVENDA_META_PATH, revenda_meta_in)
    try:
        _pri = _load_json(PRIORIZACAO_PATH, {})
        prioridade_set = {processor._norm_code(x) for x in (_pri.get("pedidos") or [])}
        df, meta = processor.process(ped_path, cfg_path, pri_path, custos_in,
                                     cif_path, custos_revenda=custos_rev_in,
                                     revenda_meta=revenda_meta_in, prioridade=prioridade_set)
        df_full, df_main, df_exc, df_fob, df_rev = processor.build_outputs_v2(df)
        out_path = os.path.join(OUT_DIR, "Analise_de_Margem.xlsx")
        excel_export.export_excel(df_full, df_main, df_exc, df_fob, meta, out_path, df_rev=df_rev)
        resumo = processor.summarize(df)
        diag = processor.diagnostics(df)
        diag["n_total"] = int(len(df_full))
        diag["n_elegiveis"] = int(len(df_main))
        diag["n_excecoes"] = int(len(df_exc))
        diag["n_fob"] = int(len(df_fob))
        diag["n_revenda"] = int(len(df_rev))
        _mf = _load_json(META_PATH, {})
        _mf["gerado"] = {"name": f"Analise_de_Margem_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx",
                         "saved": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                         "n_total": int(len(df_full))}
        _save_json(META_PATH, _mf)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    job = uuid.uuid4().hex[:8]
    return jsonify({"ok": True, "download": f"/download/{job}",
                    "resumo": resumo, "diag": diag})


@app.route("/priorizar")
def priorizar_page():
    return render_template("priorizar.html")


def _current_login():
    """Login de quem esta usando o app, derivado automaticamente.
    Le, em ordem, os cabecalhos injetados por um proxy de identidade / SSO
    (Cloudflare Access, oauth2-proxy, IAP, Nginx auth_request, etc.).
    Se o app estiver atras de um desses, o login vem sozinho - sem digitar."""
    candidatos = [
        "Cf-Access-Authenticated-User-Email",  # Cloudflare Access
        "X-Forwarded-Email",                    # oauth2-proxy / IAP
        "X-Auth-Request-Email",
        "X-Auth-Request-User",
        "X-Forwarded-User",
        "X-Forwarded-Preferred-Username",
        "Remote-User",                          # Nginx auth_request / Apache
    ]
    for h in candidatos:
        v = (request.headers.get(h) or "").strip()
        if v:
            return v
    return ""


@app.route("/carteira_pedidos")
def carteira_pedidos():
    """Devolve a carteira processada (linhas + cabecalho) para a tela de
    priorizacao, ja com a cascata de custos/MC calculada com os custos salvos."""
    cfg_path = _saved_path("config"); cif_path = _saved_path("cif")
    ped_path = _saved_pedidos()
    if not (cfg_path and cif_path):
        return jsonify({"ok": False, "error": "Salve as Fontes (Config e CIF) primeiro."}), 400
    if not ped_path:
        return jsonify({"ok": False, "error": "Carregue a carteira a faturar primeiro."}), 404
    try:
        custos_in = _load_json(CUSTOS_PATH, {})
        custos_rev_in = _load_json(CUSTOS_REV_PATH, {})
        revenda_meta_in = _load_json(REVENDA_META_PATH, {})
        df, _meta = processor.process(ped_path, cfg_path, None, custos_in, cif_path,
                                      custos_revenda=custos_rev_in,
                                      revenda_meta=revenda_meta_in, prioridade=set())
        header = [str(c) for c in df.columns]
        rows = df.where(df.notna(), "").values.tolist()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    pri = _load_json(PRIORIZACAO_PATH, {})
    return jsonify({"ok": True, "header": header, "rows": rows,
                    "priorizacao": pri, "persistente": STATE_PERSISTENTE,
                    "armazenamento": ("Banco de dados" if store.disponivel()
                                      else ("Volume" if _VOLUME_OK else "Efêmero"))})


@app.route("/priorizacao", methods=["GET", "POST"])
def priorizacao():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        pedidos = data.get("pedidos") or []
        # o login NAO vem do cliente: e o usuario autenticado de quem salvou
        login = _current_login() or "(não identificado)"
        payload = {"pedidos": [str(p) for p in pedidos],
                   "login": login,
                   "data": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")}
        _save_json(PRIORIZACAO_PATH, payload)
        return jsonify({"ok": True, **payload})
    return jsonify(_load_json(PRIORIZACAO_PATH, {"pedidos": [], "login": "", "data": ""}))


@app.route("/download/<job_id>")
def download(job_id):
    out_path = os.path.join(OUT_DIR, "Analise_de_Margem.xlsx")
    if not os.path.isfile(out_path):
        abort(404, "Arquivo ainda nao gerado.")
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    return send_file(out_path, as_attachment=True,
                     download_name=f"Analise_de_Margem_{stamp}.xlsx")


# --- Pos-redeploy: se o disco estiver vazio mas houver banco, restaura tudo ---
try:
    _rehydrate_from_db()
except Exception as _e:
    print("[N1] reidratacao geral falhou:", _e, flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
