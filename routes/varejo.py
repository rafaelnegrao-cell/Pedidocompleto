import os, json, tempfile
import pandas as pd
from flask import (
    Blueprint, render_template, current_app, request, jsonify
)

bp = Blueprint("varejo", __name__)


# ────────────────────────────────────────────────────────────────────
# Leitura de fretes — aba "Resumo por Rota"
# UF derivado do código Tabela CIF (fonte de verdade). Ex: MG-ITA-01 → MG
# ────────────────────────────────────────────────────────────────────
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

        # Tabela CIF (coluna 12 / iloc[11])
        tabela_cif = ""
        try:
            v = row.iloc[11]
            if pd.notna(v) and str(v).strip() not in ("", "nan", "None"):
                tabela_cif = str(v).strip()
        except (IndexError, KeyError):
            pass

        # UF: derivar do código Tabela CIF (MG-ITA-01 → MG)
        if tabela_cif and "-" in tabela_cif:
            estado = tabela_cif.split("-")[0]
        else:
            # fallback por número da rota (arquivos sem coluna CIF)
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
            "f2100":  _int(6),
            "f5000":  _int(7),
            "f8000":  _int(8),
            "f13100": _int(9),
            "f27000": _int(10),
        })
    return rotas if rotas else None


def _cache_path():
    return os.path.join(current_app.config["DATA_FOLDER"], "rotas_cif_cache.json")


def _carregar_rotas_cif():
    """Lê o cache de rotas (gerado ao importar o .xlsx via /upload_rotas)."""
    cache_path = _cache_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                rotas = json.load(f)
            if rotas:
                return rotas
        except Exception as e:
            print(f"[varejo] erro ao ler cache de rotas: {e}")
    return None


# ────────────────────────────────────────────────────────────────────
# Upload do arquivo de fretes (Resumo por Rota) → atualiza o cache
# ────────────────────────────────────────────────────────────────────
@bp.route("/upload_rotas", methods=["POST"])
def upload_rotas():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "erro": "Arquivo não enviado"}), 400

    cache_path = _cache_path()
    try:
        suffix = os.path.splitext(f.filename)[1] or ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name

        rotas = _rotas_from_resumo(tmp_path)
        os.unlink(tmp_path)

        if not rotas:
            return jsonify({"ok": False, "erro": "Nenhuma rota encontrada no arquivo"}), 400

        with open(cache_path, "w", encoding="utf-8") as fc:
            json.dump(rotas, fc, ensure_ascii=False)

        n_cif = sum(1 for r in rotas if r.get("tabela_cif"))
        return jsonify({"ok": True, "rotas": len(rotas), "com_cif": n_cif})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ────────────────────────────────────────────────────────────────────
# Publicação de tabela — versão standalone (persiste em JSON local)
# (No Eixo N1 ia para /performance/api/publicar-tabela; aqui é local.)
# ────────────────────────────────────────────────────────────────────
def _hist_path():
    return os.path.join(current_app.config["DATA_FOLDER"], "tabelas_publicadas.json")


@bp.route("/api/publicar-tabela", methods=["POST"])
def publicar_tabela():
    try:
        versao = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "erro": "JSON inválido"}), 400

    hist_path = _hist_path()
    hist = []
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                hist = json.load(f) or []
        except Exception:
            hist = []

    hist.append(versao)
    try:
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500

    return jsonify({"ok": True, "id": versao.get("id"), "total": len(hist)})


@bp.route("/api/tabelas-publicadas", methods=["GET"])
def tabelas_publicadas():
    hist_path = _hist_path()
    if not os.path.exists(hist_path):
        return jsonify([])
    try:
        with open(hist_path, encoding="utf-8") as f:
            return jsonify(json.load(f) or [])
    except Exception:
        return jsonify([])


# ────────────────────────────────────────────────────────────────────
# Página principal
# ────────────────────────────────────────────────────────────────────
@bp.route("/")
def index():
    rotas_cif = _carregar_rotas_cif()
    return render_template(
        "varejo.html",
        active_module="varejo",
        rotas_cif_json=json.dumps(rotas_cif, ensure_ascii=False) if rotas_cif else None,
        # No Eixo N1 estes vinham do Planejador/Pedidos Completo.
        # No standalone começam vazios; o usuário carrega via botões na tela.
        contratos_mp_json="[]",
        faturados_pre_json="null",
        faturados_nome=None,
        cidades_cif_json="[]",
    )
