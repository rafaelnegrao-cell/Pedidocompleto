"use strict";

const files = { pedidos: null, config: null, cif: null, prioridade: null };
let JOB_ID = null;

const $ = (s) => document.querySelector(s);
const fmtBRL = (v) => "R$ " + Number(v).toLocaleString("pt-BR",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const parseNum = (s) => {
  if (s === null || s === undefined) return 0;
  let t = String(s).replace(/\./g, "").replace(",", ".").replace(/[^0-9.\-]/g, "");
  const n = parseFloat(t);
  return isNaN(n) ? 0 : n;
};

/* ---------- uploads ---------- */
document.querySelectorAll('.drop input[type="file"]').forEach((inp) => {
  inp.addEventListener("change", (e) => {
    const key = inp.dataset.key;
    const f = e.target.files[0];
    files[key] = f || null;
    const drop = inp.closest(".drop");
    const fn = drop.querySelector(".fname");
    if (f) { drop.classList.add("has"); fn.textContent = f.name; }
    else { drop.classList.remove("has"); fn.textContent = ""; }
    checkReady();
  });
});

function checkReady() {
  $("#btn-analisar").disabled =
    !(files.pedidos && files.config && files.cif && files.prioridade);
}

function showMsg(sel, text, type) {
  const el = $(sel);
  el.className = "msg " + (type || "info");
  el.textContent = text;
  el.style.display = text ? "block" : "none";
}

/* ---------- etapa 1: analisar ---------- */
$("#btn-analisar").addEventListener("click", async () => {
  const btn = $("#btn-analisar");
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>Analisando…';
  showMsg("#msg-upload", "", "info");

  const fd = new FormData();
  fd.append("pedidos", files.pedidos);
  fd.append("config", files.config);
  fd.append("prioridade", files.prioridade);
  if (files.cif) fd.append("cif", files.cif);

  try {
    const r = await fetch("/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "Falha na análise.");
    JOB_ID = d.job_id;
    renderCustos(d);
  } catch (err) {
    showMsg("#msg-upload", err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Analisar Arquivos";
  }
});

/* ---------- etapa 2: render dos campos de custo ---------- */
function renderCustos(d) {
  $("#card-upload").classList.add("hidden");
  $("#card-custos").classList.remove("hidden");

  $("#resumo-pre").textContent =
    `${d.n_pedidos} linhas de pedido · ${d.mp_types.length} tipos de MP · `
    + `${d.n_priorizados} priorizados · `
    + (d.cif_ok ? `Tabela CIF OK (${d.cif_faixas} faixas de peso).`
                : `Tabela CIF não encontrada — frete usará a coluna do pedido.`);

  const grid = $("#mp-grid");
  grid.innerHTML = "";
  d.mp_types.forEach((mp, i) => {
    const row = document.createElement("div");
    row.className = "mp-row";
    row.innerHTML = `
      <div class="mp-nome">${mp}</div>
      <div class="mp-input">
        <span class="pre">R$/saca 50kg</span>
        <input type="text" inputmode="decimal" data-mp="${mp}" placeholder="0,00">
        <span class="mp-kg" data-kg="${i}">— /kg</span>
      </div>`;
    grid.appendChild(row);
  });

  grid.querySelectorAll("input[data-mp]").forEach((inp, i) => {
    inp.addEventListener("input", () => {
      const kg = parseNum(inp.value) / 50;
      grid.querySelector(`[data-kg="${i}"]`).textContent =
        kg > 0 ? fmtBRL(kg) + " /kg" : "— /kg";
    });
  });

  const semBox = $("#sem-config");
  const avisos = [];
  if (d.mp_nao_reconhecidos && d.mp_nao_reconhecidos.length) {
    avisos.push(`🔎 <strong>${d.mp_nao_reconhecidos.length}</strong> tipo(s) de MP fora da `
      + `lista padrão (verifique grafia no Config): ${d.mp_nao_reconhecidos.join(", ")}.`);
  }
  if (d.cidades_sem_rota && d.cidades_sem_rota.length) {
    const lc = d.cidades_sem_rota.slice(0, 20).join(", ");
    avisos.push(`🚚 <strong>${d.cidades_sem_rota.length}</strong> cidade(s) não localizada(s) na `
      + `Tabela de Rotas CIF (frete = 0 nesses pedidos): ${lc}`
      + `${d.cidades_sem_rota.length > 20 ? "…" : ""}`);
  }
  if (d.n_sem_config > 0) {
    const lista = d.sem_config.slice(0, 25).join(", ");
    avisos.push(`⚠️ <strong>${d.n_sem_config}</strong> código(s) de produto sem cadastro no `
      + `Config (sem MP/linha). Serão calculados com Custo MP = 0. `
      + `Ex.: ${lista}${d.n_sem_config > 25 ? "…" : ""}`);
  }
  if (avisos.length) {
    semBox.classList.remove("hidden");
    semBox.innerHTML = avisos.join("<br><br>");
  } else {
    semBox.classList.add("hidden");
  }
}

$("#btn-voltar").addEventListener("click", () => {
  $("#card-custos").classList.add("hidden");
  $("#card-upload").classList.remove("hidden");
});

/* ---------- etapa 3: gerar ---------- */
$("#btn-gerar").addEventListener("click", async () => {
  const btn = $("#btn-gerar");
  const custos = {};
  document.querySelectorAll("#mp-grid input[data-mp]").forEach((inp) => {
    custos[inp.dataset.mp] = parseNum(inp.value);
  });

  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>Gerando…';
  showMsg("#msg-custos", "", "info");

  try {
    const r = await fetch("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: JOB_ID, custos })
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "Falha ao gerar.");
    renderResult(d);
  } catch (err) {
    showMsg("#msg-custos", err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Gerar Planilha de Pedido Completo";
  }
});

function renderResult(d) {
  $("#card-custos").classList.add("hidden");
  $("#card-result").classList.remove("hidden");
  const s = d.resumo;
  const kpis = [
    { lbl: "Linhas processadas", val: s.n_linhas, cls: "azul" },
    { lbl: "Faturamento total", val: fmtBRL(s.total_venda), cls: "azul" },
    { lbl: "MC total", val: fmtBRL(s.total_mc), cls: s.total_mc < 0 ? "alerta" : "ok" },
    { lbl: "MC média", val: s.mc_medio_pct.toLocaleString("pt-BR") + "%", cls: s.mc_medio_pct < 0 ? "alerta" : "ok" },
    { lbl: "Pedidos priorizados", val: s.priorizados, cls: "azul" },
    { lbl: "Linhas com MC negativa", val: s.negativos, cls: s.negativos > 0 ? "alerta" : "ok" },
  ];
  const box = $("#kpis");
  box.innerHTML = "";
  kpis.forEach((k) => {
    const el = document.createElement("div");
    el.className = "kpi " + k.cls;
    el.innerHTML = `<div class="lbl">${k.lbl}</div><div class="val">${k.val}</div>`;
    box.appendChild(el);
  });
  $("#link-download").href = d.download;
}

$("#btn-novo").addEventListener("click", () => location.reload());
