# Eixo N1 — Simulador de Margem de Contribuição

Módulo Flask do Eixo N1 / N1 Flow que cruza **Pedidos a Faturar** × **Config de Produção**
(linha de envase, matéria-prima, nome curto) × **custos de MP e frete**, calcula a
**margem de contribuição linha a linha** e exporta a planilha **"Análise de Margem"**
formatada no padrão corporativo. Objetivo: mitigar faturamento com margem negativa e
apoiar a priorização de produção/embarque.

## Fluxo

1. **Etapa 1 — Fontes de Dados:** envia, **salva e fixa** os arquivos de referência —
   `N1_Config_Producao_Compilado`, `N1_Tabela_Rotas_CIF_Padrao` e a lista de pedidos
   priorizados. Persistem entre sessões (banner mostra os últimos salvos); só reenvie ao atualizar.
2. **Etapa 2 — Custos de MP:** os tipos de MP vêm do **Config** (aba Produtos). Informe o custo
   NET por **saca de 50 kg**; o sistema faz ÷50 → R$/kg. Os valores ficam **salvos**.
3. **Etapa 3 — Pedido a Faturar:** liberada só **após** salvar os custos. Envie o arquivo
   "A faturar" → gera e baixa a planilha **"Análise de Margem"** formatada.

O sistema sempre guarda os **últimos arquivos importados** e os **últimos custos de MP** em
`data/state/` (sources + `custos.json`).

## Regras de cálculo

| Coluna | Regra |
|---|---|
| Valor Venda c/ Imposto | coluna `Valor` do pedido |
| (-) ICMS | valor real da coluna `ICMS` do arquivo |
| (-) Custo Frete R$ | `(preço/tonelada da rota CIF / 1000) × Peso Total` (FOB = 0) |
| (-) Comissão | `(Valor − Frete) × % Comissão` |
| (-) Embalagem | valor real da coluna `Embalagem` do arquivo |
| (-) Bonificação | coluna `Bonificação R$` |
| (-) Desc. Financeiro | valor real da coluna `Desc Financ` do arquivo |
| (-) Custo MP R$ | `(custo_saca / 50) × Peso Total` |
| MC$ | Valor − soma das deduções |
| MC% | MC$ / Valor |

ICMS, Embalagem e Desc. Financeiro usam os valores já calculados pelo ERP no arquivo "A faturar"
(mais fiéis que a regra 7/12, que erra em exportação/ST). Caso a coluna não exista em outro
arquivo, há fallback: ICMS pela regra 7%/12% e Embalagem/Desc. Financeiro = 0.

### Origem e ICMS (duas plantas)

A UF de origem é definida pela coluna **Empresa/Filial** do pedido:

- `MATRIZ - ACUCAR NUMERO UM` → **PR** (Sertanópolis)
- `SP - ACUCAR NUMERO UM` → **SP** (Itaju)

ICMS interna (7%) quando a UF do cliente é igual à origem; interestadual (12%) caso contrário.
Ajuste o reconhecimento em `origem_uf_from_filial()` (`core/processor.py`).

### Frete pela Tabela de Rotas CIF

Arquivo dedicado (`N1_Tabela_Rotas_CIF_Padrao`); na falta, o sistema procura a aba dentro do
Config. Para cada linha o sistema localiza a **Cidade Destino** do pedido **filtrando pela
filial de origem** (Itaju/SP ou Sertanópolis/PR) — necessário porque ~141 cidades são
atendidas pelas duas plantas com tarifas diferentes. Registra o **Destino da Rota** e pega o
**preço por tonelada (R$/ton)** na coluna da **faixa de peso** (`Até 5.000 kg`, `Até 8.000 kg`,
…, `Acima de 25.000 kg` — faixas cumulativas: usa a menor faixa cujo limite cobre o peso).
`Custo Frete R$ = preço/t ÷ 1000 × Peso Total`. Limites em milhar BR (`25.000`) são tratados
corretamente; unidade kg/ton é detectada automaticamente. Cidades não localizadas são
sinalizadas e calculadas com frete 0. Configurável em `core/frete_cif.py`. A saída ganha as
colunas **Destino da Rota** e **Faixa Frete (R$/t)**.

## Ajuste de cabeçalhos

A detecção de colunas ignora acentos, maiúsculas, quebras de linha e espaços. Se algum
cabeçalho dos seus arquivos não for reconhecido, edite **somente** o dicionário `COLMAP`
em `core/processor.py` (adicione a variante do seu cabeçalho à lista do campo).

## Rodar localmente

```bash
pip install -r requirements.txt
python app.py          # http://localhost:8000
```

## Subir no GitHub

```bash
git init
git add .
git commit -m "Eixo N1 - Módulo de Margem de Contribuição"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/n1-margem.git
git push -u origin main
```

## Deploy no Railway

1. Railway → **New Project** → **Deploy from GitHub repo** → selecione `n1-margem`.
2. O Railway detecta Python (Nixpacks) e usa o `Procfile` / `railway.json` automaticamente.
   Start: `gunicorn app:app --bind 0.0.0.0:$PORT`.
3. Aguarde o build. Em **Settings → Networking → Generate Domain** para obter a URL pública.
4. Healthcheck já configurado em `/healthz`.

Não é preciso definir variáveis de ambiente. A porta vem de `$PORT` (injetada pelo Railway).

> Observação: o sistema de arquivos do Railway é efêmero — os arquivos de cada análise
> ficam em `data/jobs/<id>/` durante a sessão e são suficientes para o fluxo de geração/download.
> Em redeploys a pasta é zerada (o `.gitkeep` mantém a estrutura no repositório).

## Estrutura

```
n1-margem/
├── app.py                 # rotas Flask (/upload, /generate, /download)
├── core/
│   ├── columns.py         # normalização + detecção robusta de colunas
│   ├── processor.py       # cruzamento + cálculo + lista canônica de MP ← COLMAP/CANONICAL_MP aqui
│   ├── frete_cif.py       # Tabela de Rotas CIF: cidade→rota→preço/t por faixa de peso
│   └── excel_export.py    # Excel formatado (padrão N1)
├── templates/index.html
├── static/css/style.css
├── static/js/app.js
├── data/jobs/             # estado transitório por análise
├── requirements.txt · Procfile · runtime.txt · railway.json · .gitignore
```
