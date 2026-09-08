const els = {
  statusFilter: document.getElementById('statusFilter'),
  tipologiaFilter: document.getElementById('tipologiaFilter'),
  anuncianteFilter: document.getElementById('anuncianteFilter'),
  sortOrder: document.getElementById('sortOrder'),
  favoritosOnly: document.getElementById('favoritosOnlyFilter'),
  summary: document.getElementById('summary'),
  results: document.getElementById('results'),
  refreshBtn: document.getElementById('refreshBtn'),
  urlDefault: document.getElementById('urlDefault'),
  urlAtualInput: document.getElementById('urlAtualInput'),
  saveUrlBtn: document.getElementById('saveUrlBtn'),
  resetUrlBtn: document.getElementById('resetUrlBtn'),
  configMsg: document.getElementById('configMsg'),
  runScraperBtn: document.getElementById('runScraperBtn'),
  scrapeStatus: document.getElementById('scrapeStatus'),
};

let cachedData = [];
let pollTimer = null;

function statusClass(item) {
  if (item.passou_filtro === false) return 'warning';
  if (item.status.includes('CONFIRMADO')) return 'match';
  if (item.status.includes('SEM MENÇÃO')) return 'sem';
  return 'ignored';
}

function normalizarTipologia(value) {
  const raw = (value || 'Indefinida').toString().trim();
  const match = raw.match(/t?\d+[a-z]?/i);
  if (!match) return 'Indefinida';
  const clean = match[0].toUpperCase();
  if (/^T\d+[A-Z]?$/.test(clean)) return clean;
  return `T${clean.replace(/[^\d]/g, '')}`;
}

function fillSelect(selectEl, values, allLabel, allValue) {
  const selected = selectEl.value || allValue;
  const options = [allValue, ...values];
  selectEl.innerHTML = options.map(value => {
    const label = value === allValue ? allLabel : value;
    return `<option value="${value}">${label}</option>`;
  }).join('');
  selectEl.value = options.includes(selected) ? selected : allValue;
}

function formatarData(isoDate) {
  if (!isoDate) return 'Data desconhecida';
  const [ano, mes, dia] = isoDate.split('-');
  return `${dia}/${mes}/${ano}`;
}

function applyFilters(data) {
  const statusSelected = els.statusFilter.value || 'todos';
  const tipologiaSelected = els.tipologiaFilter.value || 'todas';
  const anuncianteSelected = els.anuncianteFilter.value || 'todos';
  const favoritosOnly = els.favoritosOnly.checked;

  return data.filter(item => {
    if (statusSelected !== 'todos' && item.status !== statusSelected) return false;
    if (tipologiaSelected !== 'todas' && normalizarTipologia(item.tipologia) !== tipologiaSelected) return false;
    if (anuncianteSelected !== 'todos' && (item.tipo_anunciante || 'Desconhecido') !== anuncianteSelected) return false;
    if (favoritosOnly && !item.favorito) return false;
    return true;
  });
}

function applySort(data) {
  const ordem = els.sortOrder.value || 'padrao';
  if (ordem === 'padrao') return data;

  const direcao = ordem === 'data_desc' ? -1 : 1;
  return [...data].sort((a, b) => {
    // Anúncios sem data de atualização vão sempre para o fim, independente da direção.
    if (!a.data_atualizacao && !b.data_atualizacao) return 0;
    if (!a.data_atualizacao) return 1;
    if (!b.data_atualizacao) return -1;
    return a.data_atualizacao < b.data_atualizacao ? -direcao : direcao;
  });
}

function avisoFalhaAnalise(item) {
  if (item.status === 'BLOQUEADO_POR_ANTI_BOT') {
    return 'A página caiu numa proteção anti-bot (Cloudflare, captcha, etc.) durante a varredura e não pôde ser lida corretamente.';
  }
  if (item.status === 'ERRO_TEXTO_VAZIO') {
    return 'Não foi possível extrair texto desta página durante a varredura.';
  }
  return 'A análise automática desta página falhou.';
}

function render() {
  const filtered = applySort(applyFilters(cachedData));
  const comFalha = filtered.filter(item => item.passou_filtro === false).length;
  els.summary.textContent = comFalha
    ? `${filtered.length} anúncio(s) encontrado(s) (${comFalha} com aviso de falha na análise)`
    : `${filtered.length} anúncio(s) encontrado(s)`;

  if (!filtered.length) {
    els.results.innerHTML = '<div class="empty">Nenhum anúncio para este filtro.</div>';
    return;
  }

  els.results.innerHTML = filtered.map(item => `
    <div class="card ${item.favorito ? 'is-favorito' : ''}" data-link="${item.link}">
      <div class="card-header">
        <div class="badge ${statusClass(item)}">${item.status}</div>
        <button class="fav-btn ${item.favorito ? 'active' : ''}" data-link="${item.link}" type="button" aria-pressed="${item.favorito}">
          ${item.favorito ? '★ Favorito' : '☆ Favoritar'}
        </button>
      </div>
      ${item.passou_filtro === false ? `
        <div class="warning-banner">
          ⚠️ ${avisoFalhaAnalise(item)} O status acima não reflete se este anúncio exige fiador — considere reexecutar o scraper mais tarde ou abrir o anúncio manualmente.
        </div>
      ` : ''}
      <h2 class="titulo">${item.titulo}</h2>
      <div class="meta"><strong>Tipologia:</strong> ${item.tipologia || 'Indefinida'}</div>
      <div class="meta"><strong>Anunciante:</strong> ${item.tipo_anunciante || 'Desconhecido'}</div>
      <div class="meta"><strong>Preço:</strong> ${item.preco}</div>
      <div class="meta"><strong>Atualizado em:</strong> ${formatarData(item.data_atualizacao)}</div>
      <div class="meta"><strong>Link:</strong> <a href="${item.link}" target="_blank" rel="noreferrer">Abrir anúncio</a></div>
      <div class="meta"><strong>Trecho decisivo:</strong> ${item.trecho_status || 'Sem trecho identificado'}</div>
      <div class="descricao">${item.descricao}</div>
    </div>
  `).join('');

  els.results.querySelectorAll('.fav-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleFavorite(btn.dataset.link));
  });
}

async function toggleFavorite(link) {
  try {
    const response = await fetch('/api/favorites/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ link }),
    });
    if (!response.ok) throw new Error('Não foi possível atualizar o favorito.');
    const data = await response.json();
    const item = cachedData.find(i => i.link === link);
    if (item) item.favorito = data.favorito;
    render();
  } catch (error) {
    els.configMsg.textContent = error.message;
  }
}

async function fetchResults() {
  try {
    const response = await fetch('/api/results');
    if (!response.ok) throw new Error('Resultados não encontrados. Executa o scraper primeiro.');
    cachedData = await response.json();

    fillSelect(els.statusFilter, [...new Set(cachedData.map(i => i.status))], 'Todos', 'todos');
    fillSelect(els.tipologiaFilter, [...new Set(cachedData.map(i => normalizarTipologia(i.tipologia)))], 'Todas', 'todas');
    fillSelect(els.anuncianteFilter, [...new Set(cachedData.map(i => i.tipo_anunciante || 'Desconhecido'))], 'Todos', 'todos');

    render();
  } catch (error) {
    els.summary.textContent = 'Erro ao carregar resultados';
    els.results.innerHTML = `<div class="empty">${error.message}</div>`;
  }
}

async function fetchConfig() {
  const response = await fetch('/api/config');
  const config = await response.json();
  els.urlDefault.textContent = config.url_default;
  els.urlDefault.title = config.url_default;
  els.urlAtualInput.value = config.url_atual;
  return config;
}

async function saveUrl() {
  els.configMsg.textContent = '';
  const url = els.urlAtualInput.value.trim();
  const response = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  const data = await response.json();
  if (!response.ok) {
    els.configMsg.textContent = data.erro || 'Erro ao guardar a URL.';
    return;
  }
  els.urlAtualInput.value = data.url_atual;
  els.configMsg.textContent = 'URL de busca atualizada com sucesso.';
}

async function resetUrl() {
  const response = await fetch('/api/config/reset', { method: 'POST' });
  const data = await response.json();
  els.urlAtualInput.value = data.url_atual;
  els.configMsg.textContent = 'URL restaurada para o valor padrão.';
}

function setScrapeStatusUI(status) {
  const labels = {
    idle: 'Nenhuma execução iniciada.',
    running: 'Scraper em execução... isto pode demorar alguns minutos.',
    done: status.mensagem || 'Execução concluída.',
    error: status.mensagem || 'Ocorreu um erro durante a execução.',
  };
  els.scrapeStatus.textContent = labels[status.state] || '';
  els.scrapeStatus.className = `scrape-status ${status.state}`;
  els.runScraperBtn.disabled = status.state === 'running';
}

async function pollScrapeStatus() {
  const response = await fetch('/api/scrape/status');
  const status = await response.json();
  setScrapeStatusUI(status);

  clearTimeout(pollTimer);
  if (status.state === 'running') {
    pollTimer = setTimeout(pollScrapeStatus, 3000);
  } else if (status.state === 'done') {
    fetchResults();
  }
}

async function runScraper() {
  const response = await fetch('/api/scrape', { method: 'POST' });
  const status = await response.json();
  setScrapeStatusUI(status);
  if (response.status === 409) return;
  pollScrapeStatus();
}

els.statusFilter.addEventListener('change', render);
els.tipologiaFilter.addEventListener('change', render);
els.anuncianteFilter.addEventListener('change', render);
els.sortOrder.addEventListener('change', render);
els.favoritosOnly.addEventListener('change', render);
els.refreshBtn.addEventListener('click', fetchResults);
els.saveUrlBtn.addEventListener('click', saveUrl);
els.resetUrlBtn.addEventListener('click', resetUrl);
els.runScraperBtn.addEventListener('click', runScraper);

fetchConfig();
fetchResults();
pollScrapeStatus();
