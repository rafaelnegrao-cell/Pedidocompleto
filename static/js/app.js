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
  let t = String(s).trim();
  if (!t) return 0;
  const hasC = t.includes(","), hasD = t.includes(".");
  if (hasC && hasD) t = t.replace(/\./g, "").replace(",", ".");   // BR: . milhar, , decimal
  else if (hasC) t = t.replace(",", ".");                          // só vírgula = decimal
  else if (hasD && t.split(".").length > 2) t = t.replace(/\./g, ""); // vários pontos = milhar
  // um único ponto: tratado como decimal (ex.: 86.5 -> 86.5)
  t = t.replace(/[^0-9.\-]/g, "");
  const n = parseFloat(t);
  return isNaN(n) ? 0 : n;
};
const toBR = (v) => (v === "" || v == null) ? "" : String(v).replace(".", ",");
function showMsg(sel, text, type) {
  const el = $(sel); el.className = "msg " + (type || "info");
  el.textContent = text; el.style.display = text ? "block" : "none";
}
function showView(name) {
  $("#view-import").classList.toggle("hidden", name !== "import");
  $("#view-painel").classList.toggle("hidden", name !== "painel");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

const fontes = { config: null, cif: null, prioridade: null, compras: null };
let pedidoFile = null;
let RESUMO = null;
let SAVED_CUSTOS = {};
let SAVED_CUSTOS_REV = {};
let SAVED_REVENDA_META = {};
let CONTRATOS = [];
let CONTRATOS_BY_ID = {};
let REVLINES = {};   // idx -> linha de revenda

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
    SAVED_CUSTOS_REV = d.custos_revenda || {};
    SAVED_REVENDA_META = d.revenda_meta || {};
    CONTRATOS = d.contratos || [];
    CONTRATOS_BY_ID = {}; CONTRATOS.forEach((c) => { CONTRATOS_BY_ID[c.id] = c; });
    // backup local (sobrevive a reinicios do servidor sem volume)
    try {
      const ls = JSON.parse(localStorage.getItem("n1_custos") || "{}");
      if (!Object.keys(SAVED_CUSTOS).length && ls.custos) SAVED_CUSTOS = ls.custos;
      if (!Object.keys(SAVED_CUSTOS_REV).length && ls.custos_revenda) SAVED_CUSTOS_REV = ls.custos_revenda;
      if (!Object.keys(SAVED_REVENDA_META).length && ls.revenda_meta) SAVED_REVENDA_META = ls.revenda_meta;
    } catch (e) { /* ignore */ }
    const labels = { config: "Config", cif: "CIF", prioridade: "Priorizados", compras: "Compras" };
    const partes = [];
    ["config", "cif", "prioridade", "compras"].forEach((k) => {
      if (d.sources[k]) partes.push(`${labels[k]}: <strong>${d.sources[k].name}</strong> (${d.sources[k].saved})`);
    });
    const banner = $("#banner-fontes");
    if (partes.length) { banner.style.display = "block"; banner.innerHTML = "Fontes salvas — " + partes.join(" · "); }
    else banner.style.display = "none";
    if (d.mp_err) showMsg("#msg-fontes", d.mp_err, "err");

    setCarteiraEnabled(d.fontes_ok);
    if (d.fontes_ok && d.carteira) {
      $("#carteira-status").innerHTML = `Última carteira: <strong>${d.carteira.name}</strong> (${d.carteira.saved})`;
      $("#btn-continuar").classList.remove("hidden");
    } else {
      $("#btn-continuar").classList.add("hidden");
    }
  } catch (e) { /* silencioso */ }
}

function setCarteiraEnabled(ok) {
  const card = $("#card-carteira");
  card.style.opacity = ok ? "1" : ".5";
  card.querySelectorAll("input,button").forEach((el) => { el.disabled = !ok; });
  if (ok) {
    $("#btn-carteira").disabled = !pedidoFile;
    if (!$("#btn-continuar").classList.contains("hidden")) $("#btn-continuar").disabled = false;
  } else {
    $("#carteira-status").textContent = "Salve as Fontes acima primeiro.";
  }
}

/* ---------- tela 1: salvar fontes ---------- */
$("#btn-fontes").addEventListener("click", async () => {
  const btn = $("#btn-fontes"), fd = new FormData(); let algum = false;
  ["config", "cif", "prioridade", "compras"].forEach((k) => { if (fontes[k]) { fd.append(k, fontes[k]); algum = true; } });
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

/* ---------- tela 1 -> carregar carteira e avançar ---------- */
async function carregarCarteira(useFile) {
  const btn = useFile ? $("#btn-carteira") : $("#btn-continuar");
  const txt = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Carregando…';
  showMsg("#msg-carteira", "", "info");
  try {
    let r;
    if (useFile) {
      const fd = new FormData(); fd.append("pedidos", pedidoFile);
      r = await (await fetch("/carteira", { method: "POST", body: fd })).json();
    } else {
      r = await (await fetch("/carteira")).json();
    }
    if (!r.ok) throw new Error(r.error || "Falha ao carregar carteira.");
    RESUMO = r;
    SAVED_CUSTOS = r.custos || SAVED_CUSTOS;
    SAVED_CUSTOS_REV = r.custos_revenda || SAVED_CUSTOS_REV;
    SAVED_REVENDA_META = r.revenda_meta || SAVED_REVENDA_META;
    if (r.contratos) { CONTRATOS = r.contratos; CONTRATOS_BY_ID = {}; CONTRATOS.forEach((c) => { CONTRATOS_BY_ID[c.id] = c; }); }
    renderPainel();
    showView("painel");
  } catch (err) { showMsg("#msg-carteira", err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = txt; }
}
$("#btn-carteira").addEventListener("click", () => { if (pedidoFile) carregarCarteira(true); });
$("#btn-continuar").addEventListener("click", () => carregarCarteira(false));
$("#btn-voltar").addEventListener("click", () => showView("import"));

/* ---------- abas do painel ---------- */
document.querySelectorAll(".tabbar .tab").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabbar .tab").forEach((x) => x.classList.toggle("active", x === b));
    const t = b.dataset.tab;
    ["envasado", "revenda", "consolidado"].forEach((n) =>
      $(`#pane-${n}`).classList.toggle("hidden", n !== t));
  });
});

/* ---------- coleta + auto-save dos custos ---------- */
function collectCosts() {
  const custos = {}, custos_revenda = {}, revenda_meta = {};
  document.querySelectorAll("#mp-grid input[data-mp]").forEach((i) => { custos[i.dataset.mp] = parseNum(i.value); });
  document.querySelectorAll("#rev-grid input[data-rev]").forEach((i) => { custos_revenda[i.dataset.rev] = parseNum(i.value); });
  document.querySelectorAll("#rev-grid .combo-input[data-revcontrato]").forEach((inp) => {
    const idx = inp.dataset.revcontrato, c = CONTRATOS_BY_ID[inp.dataset.selid || ""];
    revenda_meta[idx] = c
      ? { contrato_id: c.id, contrato: c.contrato, usina: c.usina, cidade_uf: c.cidade_uf, mp: c.mp }
      : { contrato_id: "", contrato: "", usina: "", cidade_uf: "" };
  });
  return { custos, custos_revenda, revenda_meta };
}
let _saveTimer = null;
function scheduleSave() { clearTimeout(_saveTimer); _saveTimer = setTimeout(doSave, 600); }
async function doSave() {
  const payload = collectCosts();
  try { localStorage.setItem("n1_custos", JSON.stringify(payload)); } catch (e) { /* ignore */ }
  try {
    await fetch("/custos", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } catch (e) { /* offline: fica salvo no localStorage */ }
}
function onCostInput() { recompute(); scheduleSave(); }

function _comboLabel(c) { return `${c.contrato} · ${c.usina}`; }
function _closeCombos(except) {
  document.querySelectorAll("#rev-grid .combo-list").forEach((l) => {
    if (l !== except) l.classList.add("hidden");
  });
}
function bindCombo(inp) {
  const idx = inp.dataset.revcontrato;
  const list = document.querySelector(`.combo-list[data-list="${idx}"]`);
  if (!list) return;
  const filtra = () => {
    const q = inp.value.trim().toLowerCase();
    list.querySelectorAll(".combo-opt").forEach((o) => {
      o.classList.toggle("hidden", q && !o.dataset.search.includes(q));
    });
  };
  inp.addEventListener("focus", () => { _closeCombos(list); list.classList.remove("hidden"); inp.select(); });
  inp.addEventListener("input", () => { list.classList.remove("hidden"); filtra(); });
  inp.addEventListener("blur", () => {
    setTimeout(() => {
      list.classList.add("hidden");
      const c = CONTRATOS_BY_ID[inp.dataset.selid || ""];
      inp.value = c ? _comboLabel(c) : "";   // restaura rótulo da selecao
    }, 180);
  });
  list.querySelectorAll(".combo-opt").forEach((opt) => {
    opt.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const c = CONTRATOS_BY_ID[opt.dataset.cid]; if (!c) return;
      inp.dataset.selid = c.id;
      inp.value = _comboLabel(c);
      list.querySelectorAll(".combo-opt").forEach((o) => o.classList.toggle("sel", o === opt));
      list.classList.add("hidden");
      const costInp = document.querySelector(`#rev-grid input[data-rev="${idx}"]`);
      if (costInp) costInp.value = toBR(Number(c.custo_saca).toFixed(2));
      const info = document.querySelector(`[data-revinfo="${idx}"]`);
      if (info) info.innerHTML = `Contrato: <strong>${c.contrato}</strong> · ${c.usina} · ${c.cidade_uf} · saldo ${Number(c.saldo_sacas).toLocaleString("pt-BR")} sc (${c.saldo_ton} t)`;
      onCostInput();
    });
  });
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".combo")) _closeCombos(null);
});

/* ---------- tela 2: painel + MC ao vivo ---------- */
function renderPainel() {
  $("#painel-carteira").textContent = `${RESUMO.n_pedidos} pedidos · ${RESUMO.n_linhas} linhas`;

  // cards de MP (envasado)
  const grid = $("#mp-grid"); grid.innerHTML = "";
  const mps = Object.keys(RESUMO.por_mp).filter((m) => RESUMO.por_mp[m].tem_mp);
  mps.forEach((mp) => {
    const info = RESUMO.por_mp[mp];
    const v = SAVED_CUSTOS[mp] != null ? SAVED_CUSTOS[mp] : "";
    const row = document.createElement("div");
    row.className = "mp-card";
    row.innerHTML = `
      <div class="mp-top"><div class="mp-nome">${mp}</div>
        <div class="mp-vol">${TON(info.peso)} · ${info.n_linhas} linha(s)</div></div>
      <div class="mp-input"><span class="pre">R$/saca 50kg</span>
        <input type="text" inputmode="decimal" data-mp="${mp}" value="${toBR(v)}" placeholder="0,00">
        <span class="mp-kg" data-kg="${mp}">— /kg</span></div>
      <div class="mp-mc" data-mc="${mp}">MC: —</div>`;
    grid.appendChild(row);
  });
  grid.querySelectorAll("input[data-mp]").forEach((inp) => inp.addEventListener("input", onCostInput));

  // cards de revenda: UMA LINHA DE PEDIDO por card (custo + usina por linha)
  const revGrid = $("#rev-grid"); revGrid.innerHTML = "";
  REVLINES = {};
  const linhas = RESUMO.revenda_linhas || [];
  $("#rev-empty").classList.toggle("hidden", linhas.length > 0);
  linhas.forEach((ln) => {
    REVLINES[ln.idx] = ln;
    const meta = SAVED_REVENDA_META[ln.idx] || {};
    const selId = meta.contrato_id || "";
    // custo: se ha contrato vinculado, usa o custo do contrato (autoritativo);
    // senao, usa o valor salvo manualmente.
    let v;
    if (selId && CONTRATOS_BY_ID[selId]) v = CONTRATOS_BY_ID[selId].custo_saca;
    else v = (SAVED_CUSTOS_REV[ln.idx] != null ? SAVED_CUSTOS_REV[ln.idx] : "");
    const pedTxt = ln.pedido ? `Pedido ${ln.pedido}` : "";
    const cliTxt = ln.cliente ? ` · ${ln.cliente}` : "";
    const selC = selId ? CONTRATOS_BY_ID[selId] : null;
    const selLabel = selC ? `${selC.contrato} · ${selC.usina}` : "";
    let optsHtml = "";
    CONTRATOS.forEach((c) => {
      const saldoTxt = c.saldo_sacas ? ` · saldo ${Number(c.saldo_sacas).toLocaleString("pt-BR")} sc (${c.saldo_ton} t)` : " · saldo 0";
      const st = c.status ? ` · ${c.status}` : "";
      const lbl = `${c.contrato} · ${c.usina} · ${c.cidade_uf} · ${c.mp} · R$ ${Number(c.custo_saca).toFixed(2)}/saca${saldoTxt}${st}`;
      const search = `${c.contrato} ${c.usina} ${c.cidade_uf} ${c.mp} ${c.status}`.toLowerCase();
      optsHtml += `<div class="combo-opt${c.id === selId ? " sel" : ""}" data-cid="${c.id}" data-search="${search.replace(/"/g, "")}">${lbl}</div>`;
    });
    const infoTxt = selC
      ? `Contrato: <strong>${selC.contrato}</strong> · ${selC.usina} · ${selC.cidade_uf} · saldo ${Number(selC.saldo_sacas).toLocaleString("pt-BR")} sc (${selC.saldo_ton} t)`
      : ((meta.usina || meta.cidade_uf) ? `Contrato: <strong>${meta.contrato || "-"}</strong> · ${meta.usina || "-"} · ${meta.cidade_uf || "-"}` : "");
    const row = document.createElement("div");
    row.className = "mp-card";
    row.innerHTML = `
      <div class="mp-top"><div class="mp-nome">${ln.nome} <span class="mp-cod">#${ln.cod}</span></div>
        <div class="mp-vol">${TON(ln.peso)}</div></div>
      <div class="rev-ped">${pedTxt}${cliTxt}</div>
      <div class="combo" data-combo="${ln.idx}">
        <input type="text" class="combo-input" data-revcontrato="${ln.idx}" data-selid="${selId}"
               value="${selLabel}" placeholder="Buscar contrato (nº, usina, cidade, MP)..." autocomplete="off" ${CONTRATOS.length ? "" : "disabled"}>
        <div class="combo-list hidden" data-list="${ln.idx}">${optsHtml || '<div class="combo-empty">Importe o Controle de Compras na Etapa 1</div>'}</div>
      </div>
      <div class="mp-input" style="margin-top:6px"><span class="pre">R$/saca 50kg</span>
        <input type="text" inputmode="decimal" data-rev="${ln.idx}" value="${toBR(v)}" placeholder="0,00">
        <span class="mp-kg" data-revkg="${ln.idx}">— /kg</span></div>
      <div class="rev-info" data-revinfo="${ln.idx}">${infoTxt}</div>
      <div class="mp-mc" data-revmc="${ln.idx}">MC: —</div>`;
    revGrid.appendChild(row);
  });
  revGrid.querySelectorAll("input[data-rev]").forEach((inp) => inp.addEventListener("input", onCostInput));
  revGrid.querySelectorAll(".combo-input").forEach(bindCombo);

  $("#link-download").classList.add("hidden");
  showMsg("#msg-pedido", "", "info");
  $("#diag-box").classList.add("hidden");
  recompute();
}

function segHead(el, label, peso, mc, valor) {
  const pct = valor ? (mc / valor) * 100 : 0;
  el.innerHTML = `<strong>${label}</strong> · ${TON(peso)} · MC <span class="${mc < 0 ? 'neg' : 'pos'}">${BRL(mc)} (${PCT(pct)})</span>`;
}

function recompute() {
  if (!RESUMO) return;
  const cmap = {};   // chave (MP ou codigo) -> R$/saca
  let totalCusto = 0;

  // envasado: cards + custo
  document.querySelectorAll("#mp-grid input[data-mp]").forEach((inp) => {
    const mp = inp.dataset.mp, info = RESUMO.por_mp[mp];
    const saca = parseNum(inp.value); cmap[mp] = saca; const kg = saca / 50;
    $(`[data-kg="${mp}"]`).textContent = saca > 0 ? BRL(kg) + " /kg" : "— /kg";
    const custoMP = kg * info.peso; totalCusto += custoMP;
    const mc = info.valor - info.outras - custoMP, mcp = info.valor ? (mc / info.valor) * 100 : 0;
    $(`[data-mc="${mp}"]`).innerHTML = `MC: <strong>${BRL(mc)}</strong> <span class="${mc < 0 ? 'neg' : 'pos'}">(${PCT(mcp)})</span>`;
  });
  // revenda: cada linha de pedido (custo + usina individuais)
  let revPeso = 0, revValor = 0, revMC = 0;
  document.querySelectorAll("#rev-grid input[data-rev]").forEach((inp) => {
    const idx = inp.dataset.rev, ln = REVLINES[idx]; if (!ln) return;
    const saca = parseNum(inp.value); const kg = saca / 50;
    $(`[data-revkg="${idx}"]`).textContent = saca > 0 ? BRL(kg) + " /kg" : "— /kg";
    const custo = kg * ln.peso; totalCusto += custo;
    const mc = ln.valor - ln.outras - custo, mcp = ln.valor ? (mc / ln.valor) * 100 : 0;
    $(`[data-revmc="${idx}"]`).innerHTML = `MC: <strong>${BRL(mc)}</strong> <span class="${mc < 0 ? 'neg' : 'pos'}">(${PCT(mcp)})</span>`;
    revPeso += ln.peso; revValor += ln.valor; revMC += mc;
  });

  // por mix (consolidado ao vivo): envasado via chaves de MP + revenda via linhas
  const mix = RESUMO.por_mix || {};
  const linhasMix = []; let envPeso = 0, envValor = 0, envMC = 0;
  Object.keys(mix).forEach((mv) => {
    const info = mix[mv];
    let custo = 0;
    Object.keys(info.chaves || {}).forEach((k) => { custo += ((cmap[k] || 0) / 50) * info.chaves[k]; });
    const mc = info.valor - info.outras - custo;
    linhasMix.push({ mv, peso: info.peso, valor: info.valor, mc });
    envPeso += info.peso; envValor += info.valor; envMC += mc;
  });
  if (revValor || revPeso) linhasMix.push({ mv: "REVENDA", peso: revPeso, valor: revValor, mc: revMC });

  segHead($("#env-head"), "Envasado (Empacotado + Especial)", envPeso, envMC, envValor);
  segHead($("#rev-head"), "Revenda (custo exato por pedido)", revPeso, revMC, revValor);

  // KPIs gerais
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
  kpis.forEach((k) => { const el = document.createElement("div"); el.className = "kpi " + k.cls;
    el.innerHTML = `<div class="lbl">${k.lbl}</div><div class="val">${k.val}</div>`; box.appendChild(el); });

  // tabela consolidada por mix
  const ord = ["AÇUCAR EMPACOTADO", "AÇUCAR ESPECIAL", "REVENDA"];
  linhasMix.sort((a, b) => (ord.indexOf(a.mv) + 99 * (ord.indexOf(a.mv) < 0)) - (ord.indexOf(b.mv) + 99 * (ord.indexOf(b.mv) < 0)));
  let html = `<table class="consol"><thead><tr><th>Mix de Produto</th><th>Volume</th><th>Faturamento</th><th>MC (R$)</th><th>MC (%)</th></tr></thead><tbody>`;
  linhasMix.forEach((l) => {
    const p = l.valor ? (l.mc / l.valor) * 100 : 0;
    html += `<tr><td>${l.mv}</td><td>${TON(l.peso)}</td><td>${BRL(l.valor)}</td><td class="${l.mc < 0 ? 'neg' : 'pos'}">${BRL(l.mc)}</td><td class="${l.mc < 0 ? 'neg' : 'pos'}">${PCT(p)}</td></tr>`;
  });
  html += `<tr class="tot"><td>TOTAL GERAL</td><td>${TON(RESUMO.total_peso)}</td><td>${BRL(RESUMO.total_valor)}</td><td class="${mcTotal < 0 ? 'neg' : 'pos'}">${BRL(mcTotal)}</td><td class="${mcTotal < 0 ? 'neg' : 'pos'}">${PCT(mcPct)}</td></tr>`;
  html += `</tbody></table>`;
  $("#consol-table").innerHTML = html;
}

/* ---------- gerar planilha ---------- */
$("#btn-gerar").addEventListener("click", async () => {
  const btn = $("#btn-gerar");
  const { custos, custos_revenda, revenda_meta } = collectCosts();
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>Gerando…';
  showMsg("#msg-pedido", "", "info");
  try {
    const d = await (await fetch("/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ custos, custos_revenda, revenda_meta }) })).json();
    if (!d.ok) throw new Error(d.error || "Falha ao gerar.");
    const g = d.diag || {}; const avisos = [];
    if (g.n_revenda != null) avisos.push(`🧾 ${g.n_revenda} pedido(s) de revenda na aba "Revenda" (custo exato de compra).`);
    if (g.n_excecoes != null) avisos.push(`📑 ${g.n_excecoes} pedido(s) na aba "Pedidos em Atenção" (sem rota / MC negativa / bloqueado não priorizado).`);
    if (g.n_fob != null) avisos.push(`🚚 ${g.n_fob} pedido(s) FOB na aba "Pedidos FOB - Retirada" (preencha a data agendada de retirada).`);
    if (g.n_sem_config) avisos.push(`🔎 ${g.n_sem_config} linha(s) com produto sem cadastro (Custo MP = 0).`);
    if (g.n_cidades_sem_rota) avisos.push(`🚚 ${g.n_cidades_sem_rota} linha(s) CIF sem cidade na Tabela de Rotas (frete = 0).`);
    const db = $("#diag-box");
    if (avisos.length) { db.classList.remove("hidden"); db.innerHTML = avisos.join("<br>"); } else db.classList.add("hidden");
    const dl = $("#link-download"); dl.href = d.download; dl.classList.remove("hidden");
    showMsg("#msg-pedido", "Planilha gerada. O download deve iniciar automaticamente.", "info");
    try {
      const a = document.createElement("a");
      a.href = d.download; a.download = "Analise_de_Margem.xlsx"; a.style.display = "none";
      document.body.appendChild(a); a.click(); setTimeout(() => a.remove(), 1000);
    } catch (e) { /* usa o botao visivel */ }
  } catch (err) { showMsg("#msg-pedido", err.message, "err"); }
  finally { btn.disabled = false; btn.textContent = "Gerar Planilha de Pedido Completo"; }
});

loadState();
