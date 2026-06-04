"use strict";

const $ = (s) => document.querySelector(s);
const BRL = (v) => "R$ " + Number(v || 0).toLocaleString("pt-BR",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const PCT = (v) => Number(v || 0).toLocaleString("pt-BR",
  { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
const TON = (kg) => (Number(kg || 0) / 1000).toLocaleString("pt-BR",
  { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " t";
const parseNum = (s) => {
  if (s == null) return 0;
  let t = String(s).replace(/\./g, "").replace(",", ".").replace(/[^0-9.\-]/g, "");
  const n = parseFloat(t); return isNaN(n) ? 0 : n;
};
function showMsg(sel, text, type) {
  const el = $(sel); el.className = "msg " + (type || "info");
  el.textContent = text; el.style.display = text ? "block" : "none";
}

const fontes = { config: null, cif: null, prioridade: null };
let pedidoFile = null;
let RESUMO = null;     // resumo da carteira
let SAVED_CUSTOS = {};

/* ---------- dropzones ---------- */
document.querySelectorAll('.drop input[type="file"]').forEach((inp) => {
  inp.addEventListener("change", (e) => {
    const key = inp.dataset.key, f = e.target.files[0] || null;
    if (key === "pedidos") pedidoFile = f; else fontes[key] = f;
    const drop = inp.closest(".drop"), fn = drop.querySelector(".fname");
    if (f) { drop.classList.add("has"); fn.textContent = f.name; }
    else { drop.classList.remove("has"); fn.textContent = ""; }
    if (key === "pedidos") $("#btn-carteira").disabled = !pedidoFile;
  });
});

/* ---------- estado persistido ---------- */
async function loadState() {
  try {
    const d = await (await fetch("/state")).json();
    SAVED_CUSTOS = d.custos || {};
    const labels = { config: "Config", cif: "CIF", prioridade: "Priorizados" };
    const partes = [];
    Object.keys(labels).forEach((k) => {
      if (d.sources[k]) partes.push(`${labels[k]}: <strong>${d.sources[k].name}</strong> (${d.sources[k].saved})`);
    });
    const banner = $("#banner-fontes");
    if (partes.length) { banner.style.display = "block"; banner.innerHTML = "Fontes salvas — " + partes.join(" · "); }
    else banner.style.display = "none";
    if (d.mp_err) showMsg("#msg-fontes", d.mp_err, "err");

    setCarteiraEnabled(d.fontes_ok);
    // recarrega última carteira salva, se houver
    if (d.fontes_ok && d.carteira) {
      $("#carteira-status").innerHTML = `Última carteira: <strong>${d.carteira.name}</strong> (${d.carteira.saved})`;
      const r = await (await fetch("/carteira")).json();
      if (r.ok) { RESUMO = r; SAVED_CUSTOS = r.custos || SAVED_CUSTOS; renderPainel(); }
    }
  } catch (e) { /* silencioso */ }
}

function setCarteiraEnabled(ok) {
  const card = $("#card-carteira");
  card.style.opacity = ok ? "1" : ".5";
  card.querySelectorAll("input,button").forEach((el) => { el.disabled = !ok; });
  if (ok) $("#btn-carteira").disabled = !pedidoFile;
  if (!ok) $("#carteira-status").textContent = "Salve as Fontes na Etapa 1 primeiro.";
}

/* ---------- etapa 1 ---------- */
$("#btn-fontes").addEventListener("click", async () => {
  const btn = $("#btn-fontes"), fd = new FormData(); let algum = false;
  ["config", "cif", "prioridade"].forEach((k) => { if (fontes[k]) { fd.append(k, fontes[k]); algum = true; } });
  if (!algum) { showMsg("#msg-fontes", "Selecione ao menos um arquivo.", "err"); return; }
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Salvando…';
  try {
    const d = await (await fetch("/sources", { method: "POST", body: fd })).json();
    if (!d.ok) throw new Error(d.error || "Falha ao salvar.");
    showMsg("#msg-fontes", "Fontes salvas e fixadas.", "info");
    await loadState();
  } catch (err) { showMsg("#msg-fontes", err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Salvar Fontes"; }
});

/* ---------- etapa 2: carregar carteira ---------- */
$("#btn-carteira").addEventListener("click", async () => {
  if (!pedidoFile) return;
  const btn = $("#btn-carteira");
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Carregando…';
  showMsg("#msg-carteira", "", "info");
  const fd = new FormData(); fd.append("pedidos", pedidoFile);
  try {
    const r = await (await fetch("/carteira", { method: "POST", body: fd })).json();
    if (!r.ok) throw new Error(r.error || "Falha ao carregar carteira.");
    RESUMO = r; SAVED_CUSTOS = r.custos || SAVED_CUSTOS;
    renderPainel();
  } catch (err) { showMsg("#msg-carteira", err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Carregar Carteira"; }
});

/* ---------- painel + MC ao vivo ---------- */
function renderPainel() {
  $("#painel").classList.remove("hidden");

  // cards de MP (somente os com cadastro de MP)
  const grid = $("#mp-grid"); grid.innerHTML = "";
  const mps = Object.keys(RESUMO.por_mp).filter((m) => RESUMO.por_mp[m].tem_mp);
  mps.forEach((mp) => {
    const info = RESUMO.por_mp[mp];
    const v = SAVED_CUSTOS[mp] != null ? SAVED_CUSTOS[mp] : "";
    const row = document.createElement("div");
    row.className = "mp-card";
    row.innerHTML = `
      <div class="mp-top">
        <div class="mp-nome">${mp}</div>
        <div class="mp-vol">${TON(info.peso)} · ${info.n_linhas} linha(s)</div>
      </div>
      <div class="mp-input">
        <span class="pre">R$/saca 50kg</span>
        <input type="text" inputmode="decimal" data-mp="${mp}" value="${v}" placeholder="0,00">
        <span class="mp-kg" data-kg="${mp}">— /kg</span>
      </div>
      <div class="mp-mc" data-mc="${mp}">MC: —</div>`;
    grid.appendChild(row);
  });
  grid.querySelectorAll("input[data-mp]").forEach((inp) => {
    inp.addEventListener("input", recompute);
  });
  recompute();
}

function recompute() {
  if (!RESUMO) return;
  let totalCusto = 0;
  document.querySelectorAll("#mp-grid input[data-mp]").forEach((inp) => {
    const mp = inp.dataset.mp, info = RESUMO.por_mp[mp];
    const saca = parseNum(inp.value), kg = saca / 50;
    $(`[data-kg="${mp}"]`).textContent = saca > 0 ? BRL(kg) + " /kg" : "— /kg";
    const custoMP = kg * info.peso;
    totalCusto += custoMP;
    const mc = info.valor - info.outras - custoMP;
    const mcp = info.valor ? (mc / info.valor) * 100 : 0;
    const el = $(`[data-mc="${mp}"]`);
    el.innerHTML = `MC: <strong>${BRL(mc)}</strong> <span class="${mc < 0 ? 'neg' : 'pos'}">(${PCT(mcp)})</span>`;
  });

  const mcTotal = RESUMO.total_valor - RESUMO.total_outras - totalCusto;
  const mcPct = RESUMO.total_valor ? (mcTotal / RESUMO.total_valor) * 100 : 0;

  const kpis = [
    { lbl: "Valor total a faturar", val: BRL(RESUMO.total_valor), cls: "azul" },
    { lbl: "Peso total a faturar", val: TON(RESUMO.total_peso), cls: "azul" },
    { lbl: "CIF · FOB", val: `${PCT(RESUMO.pct_cif)} · ${PCT(RESUMO.pct_fob)}`, cls: "azul" },
    { lbl: "Liberado · Bloqueado", val: `${PCT(RESUMO.pct_liberado)} · ${PCT(RESUMO.pct_bloqueado)}`, cls: "azul" },
    { lbl: "MC total", val: BRL(mcTotal), cls: mcTotal < 0 ? "alerta" : "ok" },
    { lbl: "MC %", val: PCT(mcPct), cls: mcPct < 0 ? "alerta" : "ok" },
  ];
  const box = $("#kpis-topo"); box.innerHTML = "";
  kpis.forEach((k) => {
    const el = document.createElement("div");
    el.className = "kpi " + k.cls;
    el.innerHTML = `<div class="lbl">${k.lbl}</div><div class="val">${k.val}</div>`;
    box.appendChild(el);
  });
}

/* ---------- gerar planilha ---------- */
$("#btn-gerar").addEventListener("click", async () => {
  const btn = $("#btn-gerar");
  const custos = {};
  document.querySelectorAll("#mp-grid input[data-mp]").forEach((inp) => {
    custos[inp.dataset.mp] = parseNum(inp.value);
  });
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Gerando…';
  showMsg("#msg-pedido", "", "info");
  try {
    const d = await (await fetch("/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ custos }) })).json();
    if (!d.ok) throw new Error(d.error || "Falha ao gerar.");
    const g = d.diag || {}; const avisos = [];
    if (g.n_excecoes != null) avisos.push(`📑 ${g.n_excecoes} pedido(s) na aba "Pedidos em Atenção" (sem rota / MC negativa / bloqueado não priorizado).`);
    if (g.n_sem_config) avisos.push(`🔎 ${g.n_sem_config} linha(s) com produto sem cadastro (Custo MP = 0).`);
    if (g.n_cidades_sem_rota) avisos.push(`🚚 ${g.n_cidades_sem_rota} linha(s) CIF sem cidade na Tabela de Rotas (frete = 0).`);
    const db = $("#diag-box");
    if (avisos.length) { db.classList.remove("hidden"); db.innerHTML = avisos.join("<br>"); } else db.classList.add("hidden");
    const dl = $("#link-download"); dl.href = d.download; dl.classList.remove("hidden");
    showMsg("#msg-pedido", "Planilha gerada.", "info");
  } catch (err) { showMsg("#msg-pedido", err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Gerar Planilha de Pedido Completo"; }
});

loadState();
