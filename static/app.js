const els = {
  fontesContainer: document.getElementById('fontesContainer'),
  searchInput: document.getElementById('searchInput'),
  fonteFilter: document.getElementById('fonteFilter'),
  concelhoFilter: document.getElementById('concelhoFilter'),
  freguesiaFilter: document.getElementById('freguesiaFilter'),
  statusFilter: document.getElementById('statusFilter'),
  tipologiaFilter: document.getElementById('tipologiaFilter'),
  anuncianteFilter: document.getElementById('anuncianteFilter'),
  precoMinFilter: document.getElementById('precoMinFilter'),
  precoMaxFilter: document.getElementById('precoMaxFilter'),
  sortOrder: document.getElementById('sortOrder'),
  favoritosOnly: document.getElementById('favoritosOnlyFilter'),
  favoritosCount: document.getElementById('favoritosCount'),
  verOcultos: document.getElementById('verOcultosFilter'),
  ocultosCount: document.getElementById('ocultosCount'),
  summary: document.getElementById('summary'),
  results: document.getElementById('results'),
  refreshBtn: document.getElementById('refreshBtn'),
  toast: document.getElementById('toast'),
  toggleConfigBtn: document.getElementById('toggleConfigBtn'),
  toggleFiltersBtn: document.getElementById('toggleFiltersBtn'),
  toggleMapBtn: document.getElementById('toggleMapBtn'),
  mapView: document.getElementById('mapView'),
  mapNote: document.getElementById('mapNote'),
};

function initCollapsible(wrapperId, btn, storageKey, defaultExpanded, aoExpandir) {
  const wrapper = document.getElementById(wrapperId);
  let expanded = defaultExpanded;
  try {
    const salvo = localStorage.getItem(storageKey);
    if (salvo !== null) expanded = salvo === '1';
  } catch (error) {
    // localStorage pode estar indisponível (ex.: modo privado); segue com o padrão.
  }

  const aplicar = () => {
    wrapper.classList.toggle('expanded', expanded);
    btn.classList.toggle('active', expanded);
    btn.setAttribute('aria-expanded', String(expanded));
    // O conteúdo só tem tamanho real depois da transição do collapsible
    // terminar — importante pro Leaflet, que mede o container ao iniciar.
    if (expanded && aoExpandir) setTimeout(aoExpandir, 300);
  };
  aplicar();

  btn.addEventListener('click', () => {
    expanded = !expanded;
    aplicar();
    try {
      localStorage.setItem(storageKey, expanded ? '1' : '0');
    } catch (error) {
      // Sem persistência disponível: a preferência só vale para esta sessão.
    }
  });
}

// ---- Mapa -------------------------------------------------------------

const PORTO_CENTRO = [41.1579, -8.6291];
const RAIO_APROXIMADO_METROS = 450;

let leafletMap = null;
let leafletMarcadores = null;
let ultimoFiltrado = [];

function initMapaSeNecessario() {
  if (leafletMap) {
    leafletMap.invalidateSize();
    return;
  }
  leafletMap = L.map(els.mapView).setView(PORTO_CENTRO, 12);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(leafletMap);
  leafletMarcadores = L.layerGroup().addTo(leafletMap);
  atualizarMarcadoresDoMapa(ultimoFiltrado);
}

function popupDoAnuncio(item) {
  const avisoAproximado = item.localizacao.preciso ? '' : ' <em>(localização aproximada)</em>';
  return `
    <strong>${item.titulo}</strong><br>
    ${item.preco}${avisoAproximado}<br>
    <a href="${item.link}" target="_blank" rel="noreferrer">Abrir anúncio ↗</a>
  `;
}

function atualizarMarcadoresDoMapa(itens) {
  if (!leafletMap) return;
  leafletMarcadores.clearLayers();

  const localizados = itens.filter(item => {
    const loc = item.localizacao;
    return loc && Number.isFinite(loc.lat) && Number.isFinite(loc.lon);
  });

  localizados.forEach(item => {
    const { lat, lon, preciso } = item.localizacao;
    const camada = preciso
      ? L.marker([lat, lon])
      : L.circle([lat, lon], {
          radius: RAIO_APROXIMADO_METROS,
          color: '#4f46e5',
          fillColor: '#4f46e5',
          fillOpacity: 0.18,
          weight: 1.5,
        });
    camada.bindPopup(popupDoAnuncio(item));
    leafletMarcadores.addLayer(camada);
  });

  els.mapNote.textContent = itens.length
    ? `Mostrando ${localizados.length} de ${itens.length} anúncio(s) filtrado(s) no mapa — os demais não têm localização identificada.`
    : 'Nenhum anúncio para este filtro.';
}

let toastTimer = null;

function esconderToast() {
  clearTimeout(toastTimer);
  els.toast.classList.remove('show');
}

function mostrarToast(mensagem, { textoAcao, aoAcionar } = {}) {
  clearTimeout(toastTimer);
  els.toast.innerHTML = `<span>${mensagem}</span>` + (textoAcao ? `<button type="button" class="toast-action">${textoAcao}</button>` : '');
  if (textoAcao && aoAcionar) {
    els.toast.querySelector('.toast-action').addEventListener('click', () => {
      esconderToast();
      aoAcionar();
    });
  }
  els.toast.classList.add('show');
  toastTimer = setTimeout(esconderToast, 5000);
}

let cachedData = [];
let fonteLabels = {};
let pollTimer = null;
let pollCheckTimer = null;
let ultimoEstadoPorFonte = {};
let ultimoEstadoCheckPorFonte = {};

function statusClass(item) {
  if (item.passou_filtro === false) return 'warning';
  if (item.status.includes('CONFIRMADO')) return 'match';
  if (item.status.includes('SEM MENÇÃO')) return 'sem';
  return 'ignored';
}

function rotuloFonte(fonte) {
  return fonteLabels[fonte] || fonte;
}

function normalizarTipologia(value) {
  const raw = (value || 'Indefinida').toString().trim();
  const match = raw.match(/t?\d+[a-z]?/i);
  if (!match) return 'Indefinida';
  const clean = match[0].toUpperCase();
  if (/^T\d+[A-Z]?$/.test(clean)) return clean;
  return `T${clean.replace(/[^\d]/g, '')}`;
}

function fillSelect(selectEl, values, allLabel, allValue, labelFor) {
  const selected = selectEl.value || allValue;
  const options = [allValue, ...values];
  selectEl.innerHTML = options.map(value => {
    const label = value === allValue ? allLabel : (labelFor ? labelFor(value) : value);
    return `<option value="${value}">${label}</option>`;
  }).join('');
  selectEl.value = options.includes(selected) ? selected : allValue;
}

function formatarData(isoDate) {
  if (!isoDate) return 'Data desconhecida';
  const [ano, mes, dia] = isoDate.split('-');
  return `${dia}/${mes}/${ano}`;
}

function parsePreco(precoStr) {
  if (!precoStr) return null;
  const match = precoStr.match(/[\d.,]+/);
  if (!match) return null;

  // Formato português: "." separa milhares, "," separa decimais.
  let numStr = match[0];
  numStr = numStr.includes(',') ? numStr.replace(/\./g, '').replace(',', '.') : numStr.replace(/\./g, '');

  const valor = parseFloat(numStr);
  return Number.isFinite(valor) ? valor : null;
}

function applyFilters(data) {
  const termoBusca = els.searchInput.value.trim().toLowerCase();
  const fonteSelected = els.fonteFilter.value || 'todas';
  const concelhoSelected = els.concelhoFilter.value || 'todos';
  const freguesiaSelected = els.freguesiaFilter.value || 'todas';
  const statusSelected = els.statusFilter.value || 'todos';
  const tipologiaSelected = els.tipologiaFilter.value || 'todas';
  const anuncianteSelected = els.anuncianteFilter.value || 'todos';
  const favoritosOnly = els.favoritosOnly.checked;
  const verOcultos = els.verOcultos.checked;
  const precoMin = els.precoMinFilter.value !== '' ? parseFloat(els.precoMinFilter.value) : null;
  const precoMax = els.precoMaxFilter.value !== '' ? parseFloat(els.precoMaxFilter.value) : null;

  return data.filter(item => {
    // Por padrão, anúncios ocultos ficam fora da listagem; "Ver ocultos" inverte
    // para mostrar só esses, permitindo revisá-los (e desocultá-los se quiser).
    if (verOcultos ? !item.oculto : item.oculto) return false;
    if (termoBusca) {
      const textoPesquisavel = `${item.titulo} ${item.descricao} ${item.trecho_status || ''}`.toLowerCase();
      if (!textoPesquisavel.includes(termoBusca)) return false;
    }
    if (fonteSelected !== 'todas' && item.fonte !== fonteSelected) return false;
    // Sem localização identificada, não há como confirmar concelho/freguesia
    // — o anúncio fica de fora quando esses filtros estão ativos, mesma regra
    // já usada para o filtro de preço quando o valor não foi reconhecido.
    if (concelhoSelected !== 'todos' && (item.localizacao?.concelho || null) !== concelhoSelected) return false;
    if (freguesiaSelected !== 'todas' && (item.localizacao?.freguesia || null) !== freguesiaSelected) return false;
    if (statusSelected !== 'todos' && item.status !== statusSelected) return false;
    if (tipologiaSelected !== 'todas' && normalizarTipologia(item.tipologia) !== tipologiaSelected) return false;
    if (anuncianteSelected !== 'todos' && (item.tipo_anunciante || 'Desconhecido') !== anuncianteSelected) return false;
    if (favoritosOnly && !item.favorito) return false;
    if (precoMin !== null || precoMax !== null) {
      const precoNum = parsePreco(item.preco);
      // Preço não identificado (ex.: "N/A") fica de fora quando o filtro de preço está ativo,
      // já que não há como confirmar se ele está dentro da faixa escolhida.
      if (precoNum === null) return false;
      if (precoMin !== null && precoNum < precoMin) return false;
      if (precoMax !== null && precoNum > precoMax) return false;
    }
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

  const totalFavoritos = cachedData.filter(item => item.favorito).length;
  const totalOcultos = cachedData.filter(item => item.oculto).length;
  els.favoritosCount.textContent = totalFavoritos ? `(${totalFavoritos})` : '';
  els.ocultosCount.textContent = totalOcultos ? `(${totalOcultos})` : '';

  ultimoFiltrado = filtered;
  if (leafletMap) atualizarMarcadoresDoMapa(filtered);

  if (!filtered.length) {
    const mensagemVazio = els.verOcultos.checked
      ? 'Nenhum anúncio oculto no momento.'
      : 'Nenhum anúncio para este filtro.';
    els.results.innerHTML = `<div class="empty">${mensagemVazio}</div>`;
    return;
  }

  els.results.innerHTML = filtered.map(item => `
    <div class="card ${item.favorito ? 'is-favorito' : ''}" data-link="${item.link}">
      <div class="card-header">
        <div class="badges">
          <div class="badge ${statusClass(item)}">${item.status}</div>
          <div class="badge fonte">${rotuloFonte(item.fonte)}</div>
        </div>
        <div class="card-actions">
          <button class="fav-btn ${item.favorito ? 'active' : ''}" data-link="${item.link}" type="button" aria-pressed="${item.favorito}" title="${item.favorito ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}">
            ${item.favorito ? '★ Favorito' : '☆ Favoritar'}
          </button>
          <button class="hide-btn ${item.oculto ? 'active' : ''}" data-link="${item.link}" type="button" aria-pressed="${item.oculto}" title="${item.oculto ? 'Voltar a mostrar este anúncio na lista' : 'Tirar este anúncio da lista sem apagá-lo'}">
            ${item.oculto ? '🔁 Mostrar' : '🙈 Ocultar'}
          </button>
        </div>
      </div>
      ${item.passou_filtro === false ? `
        <div class="warning-banner">
          ⚠️ ${avisoFalhaAnalise(item)} O status acima não reflete se este anúncio exige fiador — considere reexecutar o scraper mais tarde ou abrir o anúncio manualmente.
        </div>
      ` : ''}
      <h2 class="titulo">${item.titulo}</h2>
      <div class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">Preço</span>
          <span class="meta-value price">${item.preco}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Tipologia</span>
          <span class="meta-value">${item.tipologia || 'Indefinida'}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Anunciante</span>
          <span class="meta-value">${item.tipo_anunciante || 'Desconhecido'}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Atualizado</span>
          <span class="meta-value">${formatarData(item.data_atualizacao)}</span>
        </div>
      </div>
      ${item.trecho_status ? `<blockquote class="trecho">${item.trecho_status}</blockquote>` : ''}
      <div class="descricao" title="Clique para expandir/recolher a descrição completa">${item.descricao}</div>
      <div class="card-footer">
        <a class="card-link" href="${item.link}" target="_blank" rel="noreferrer">Abrir anúncio ↗</a>
      </div>
    </div>
  `).join('');

  els.results.querySelectorAll('.fav-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleFavorite(btn.dataset.link));
  });
  els.results.querySelectorAll('.hide-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleHidden(btn.dataset.link));
  });
  els.results.querySelectorAll('.descricao').forEach(el => {
    el.addEventListener('click', () => el.classList.toggle('expanded'));
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
    console.error(error);
  }
}

async function toggleHidden(link) {
  try {
    const response = await fetch('/api/hidden/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ link }),
    });
    if (!response.ok) throw new Error('Não foi possível ocultar/reexibir o anúncio.');
    const data = await response.json();
    const item = cachedData.find(i => i.link === link);
    if (item) item.oculto = data.oculto;
    render();
    // Ocultar não apaga nada no backend, mas ainda assim é fácil de fazer
    // sem querer — o "Desfazer" evita ter de ligar "Ver ocultos" só para reverter.
    if (data.oculto) {
      mostrarToast('Anúncio ocultado.', { textoAcao: 'Desfazer', aoAcionar: () => toggleHidden(link) });
    }
  } catch (error) {
    console.error(error);
  }
}

function ordemAlfabetica(valores) {
  return [...valores].sort((a, b) => a.localeCompare(b, 'pt'));
}

function concelhosDisponiveis() {
  return cachedData.map(item => item.localizacao?.concelho).filter(Boolean);
}

function freguesiasDisponiveis() {
  // A freguesia só faz sentido dentro do concelho escolhido — trocar o
  // concelho sempre recalcula as opções pra não sobrar uma freguesia de
  // outro concelho selecionada.
  const concelhoSelecionado = els.concelhoFilter.value || 'todos';
  return cachedData
    .filter(item => concelhoSelecionado === 'todos' || item.localizacao?.concelho === concelhoSelecionado)
    .map(item => item.localizacao?.freguesia)
    .filter(Boolean);
}

function atualizarOpcoesDeFreguesia() {
  fillSelect(els.freguesiaFilter, ordemAlfabetica([...new Set(freguesiasDisponiveis())]), 'Todas', 'todas');
}

async function fetchResults() {
  try {
    const response = await fetch('/api/results');
    if (!response.ok) throw new Error('Resultados não encontrados. Executa um scraper primeiro.');
    cachedData = await response.json();

    fillSelect(els.fonteFilter, [...new Set(cachedData.map(i => i.fonte))], 'Todas', 'todas', rotuloFonte);
    fillSelect(els.concelhoFilter, ordemAlfabetica([...new Set(concelhosDisponiveis())]), 'Todos', 'todos');
    atualizarOpcoesDeFreguesia();
    fillSelect(els.statusFilter, [...new Set(cachedData.map(i => i.status))], 'Todos', 'todos');
    fillSelect(els.tipologiaFilter, [...new Set(cachedData.map(i => normalizarTipologia(i.tipologia)))], 'Todas', 'todas');
    fillSelect(els.anuncianteFilter, [...new Set(cachedData.map(i => i.tipo_anunciante || 'Desconhecido'))], 'Todos', 'todos');

    render();
  } catch (error) {
    els.summary.textContent = 'Erro ao carregar resultados';
    els.results.innerHTML = `<div class="empty">${error.message}</div>`;
  }
}

function painelFonteHTML(fonte, dados) {
  return `
    <section class="panel" data-fonte="${fonte}">
      <h2 class="panel-title">Configuração da busca — ${dados.label}</h2>
      <div class="config-row">
        <span class="config-label">URL padrão:</span>
        <span class="url-default" title="${dados.url_default}">${dados.url_default}</span>
      </div>
      <div class="config-row">
        <label class="config-label">URL atual:</label>
        <input type="text" class="url-input url-atual-input" value="${dados.url_atual}" />
      </div>
      <div class="config-actions">
        <button type="button" class="save-url-btn">Guardar URL</button>
        <button type="button" class="secondary reset-url-btn">Restaurar padrão</button>
        <button type="button" class="primary run-scraper-btn">Executar scraper</button>
      </div>
      <div class="config-msg"></div>
      <div class="scrape-status idle"></div>
      <div class="progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" hidden>
        <div class="progress-bar-fill"></div>
      </div>
      <div class="check-actions">
        <button type="button" class="secondary run-check-btn">Verificar anúncios ativos</button>
      </div>
      <p class="check-hint">Remove definitivamente da lista os anúncios que já saíram do ar (arrendados ou removidos pelo anunciante).</p>
      <div class="check-status idle"></div>
      <div class="progress-bar check-progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" hidden>
        <div class="progress-bar-fill"></div>
      </div>
    </section>
  `;
}

async function fetchConfig() {
  const response = await fetch('/api/config');
  const config = await response.json();

  fonteLabels = Object.fromEntries(Object.entries(config).map(([fonte, dados]) => [fonte, dados.label]));
  els.fontesContainer.innerHTML = Object.entries(config).map(([fonte, dados]) => painelFonteHTML(fonte, dados)).join('');

  return config;
}

async function saveUrl(fonte, painel) {
  const msgEl = painel.querySelector('.config-msg');
  const inputEl = painel.querySelector('.url-atual-input');
  msgEl.textContent = '';

  const url = inputEl.value.trim();
  const response = await fetch(`/api/config/${fonte}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  const data = await response.json();
  if (!response.ok) {
    msgEl.textContent = data.erro || 'Erro ao guardar a URL.';
    return;
  }
  inputEl.value = data.url_atual;
  msgEl.textContent = 'URL de busca atualizada com sucesso.';
}

async function resetUrl(fonte, painel) {
  const response = await fetch(`/api/config/${fonte}/reset`, { method: 'POST' });
  const data = await response.json();
  painel.querySelector('.url-atual-input').value = data.url_atual;
  painel.querySelector('.config-msg').textContent = 'URL restaurada para o valor padrão.';
}

function formatarEta(segundos) {
  if (segundos === null || segundos === undefined) return '';
  if (segundos < 60) return `~${Math.max(1, Math.round(segundos))}s restantes`;
  const minutos = Math.round(segundos / 60);
  return `~${minutos} min restante${minutos === 1 ? '' : 's'}`;
}

function atualizarPainelDeStatus(fonte, status) {
  const painel = els.fontesContainer.querySelector(`[data-fonte="${fonte}"]`);
  if (!painel) return;

  const labels = {
    idle: 'Nenhuma execução iniciada.',
    running: status.mensagem || 'Scraper em execução...',
    done: status.mensagem || 'Execução concluída.',
    error: status.mensagem || 'Ocorreu um erro durante a execução.',
  };
  let texto = labels[status.state] || '';
  const emProgresso = status.state === 'running' && status.total;
  if (emProgresso) {
    const eta = formatarEta(status.eta_segundos);
    if (eta) texto += ` (${eta})`;
  }

  const statusEl = painel.querySelector('.scrape-status');
  statusEl.textContent = texto;
  statusEl.className = `scrape-status ${status.state}`;
  painel.querySelector('.run-scraper-btn').disabled = status.state === 'running';

  const barraEl = painel.querySelector('.progress-bar');
  barraEl.hidden = !emProgresso;
  if (emProgresso) {
    const pct = Math.min(100, Math.round((status.atual / status.total) * 100));
    barraEl.querySelector('.progress-bar-fill').style.width = `${pct}%`;
    barraEl.setAttribute('aria-valuenow', String(pct));
  }
}

async function pollScrapeStatus() {
  const response = await fetch('/api/scrape/status');
  const statusPorFonte = await response.json();

  let algumaEmExecucao = false;
  let algumaAcabouDeConcluir = false;

  for (const [fonte, status] of Object.entries(statusPorFonte)) {
    atualizarPainelDeStatus(fonte, status);
    if (status.state === 'running') algumaEmExecucao = true;
    if (status.state === 'done' && ultimoEstadoPorFonte[fonte] === 'running') algumaAcabouDeConcluir = true;
    ultimoEstadoPorFonte[fonte] = status.state;
  }

  if (algumaAcabouDeConcluir) fetchResults();

  clearTimeout(pollTimer);
  if (algumaEmExecucao) {
    pollTimer = setTimeout(pollScrapeStatus, 3000);
  }
}

async function runScraper(fonte, painel) {
  const response = await fetch(`/api/scrape/${fonte}`, { method: 'POST' });
  const status = await response.json();
  atualizarPainelDeStatus(fonte, status);
  if (response.status === 409) return;
  ultimoEstadoPorFonte[fonte] = 'running';
  pollScrapeStatus();
}

function atualizarPainelDeCheckStatus(fonte, status) {
  const painel = els.fontesContainer.querySelector(`[data-fonte="${fonte}"]`);
  if (!painel) return;

  const labels = {
    idle: 'Nenhuma verificação de disponibilidade realizada ainda.',
    running: status.mensagem || 'Verificando anúncios ativos...',
    done: status.mensagem || 'Verificação concluída.',
    error: status.mensagem || 'Ocorreu um erro durante a verificação.',
  };
  let texto = labels[status.state] || '';
  const emProgresso = status.state === 'running' && status.total;
  if (emProgresso) {
    const eta = formatarEta(status.eta_segundos);
    if (eta) texto += ` (${eta})`;
  }

  const statusEl = painel.querySelector('.check-status');
  statusEl.textContent = texto;
  statusEl.className = `check-status ${status.state}`;
  painel.querySelector('.run-check-btn').disabled = status.state === 'running';

  const barraEl = painel.querySelector('.check-progress-bar');
  barraEl.hidden = !emProgresso;
  if (emProgresso) {
    const pct = Math.min(100, Math.round((status.atual / status.total) * 100));
    barraEl.querySelector('.progress-bar-fill').style.width = `${pct}%`;
    barraEl.setAttribute('aria-valuenow', String(pct));
  }
}

async function pollCheckStatus() {
  const response = await fetch('/api/check/status');
  const statusPorFonte = await response.json();

  let algumaEmExecucao = false;
  let algumaAcabouDeConcluir = false;

  for (const [fonte, status] of Object.entries(statusPorFonte)) {
    atualizarPainelDeCheckStatus(fonte, status);
    if (status.state === 'running') algumaEmExecucao = true;
    if (status.state === 'done' && ultimoEstadoCheckPorFonte[fonte] === 'running') algumaAcabouDeConcluir = true;
    ultimoEstadoCheckPorFonte[fonte] = status.state;
  }

  // Anúncios podem ter sido removidos definitivamente nesta verificação.
  if (algumaAcabouDeConcluir) fetchResults();

  clearTimeout(pollCheckTimer);
  if (algumaEmExecucao) {
    pollCheckTimer = setTimeout(pollCheckStatus, 3000);
  }
}

async function runCheck(fonte) {
  const response = await fetch(`/api/check/${fonte}`, { method: 'POST' });
  const status = await response.json();
  atualizarPainelDeCheckStatus(fonte, status);
  if (response.status === 409) return;
  ultimoEstadoCheckPorFonte[fonte] = 'running';
  pollCheckStatus();
}

els.fontesContainer.addEventListener('click', event => {
  const painel = event.target.closest('[data-fonte]');
  if (!painel) return;
  const fonte = painel.dataset.fonte;

  if (event.target.classList.contains('save-url-btn')) saveUrl(fonte, painel);
  else if (event.target.classList.contains('reset-url-btn')) resetUrl(fonte, painel);
  else if (event.target.classList.contains('run-scraper-btn')) runScraper(fonte, painel);
  else if (event.target.classList.contains('run-check-btn')) runCheck(fonte);
});

els.searchInput.addEventListener('input', render);
els.fonteFilter.addEventListener('change', render);
els.concelhoFilter.addEventListener('change', () => {
  atualizarOpcoesDeFreguesia();
  render();
});
els.freguesiaFilter.addEventListener('change', render);
els.statusFilter.addEventListener('change', render);
els.tipologiaFilter.addEventListener('change', render);
els.anuncianteFilter.addEventListener('change', render);
els.precoMinFilter.addEventListener('input', render);
els.precoMaxFilter.addEventListener('input', render);
els.sortOrder.addEventListener('change', render);
els.favoritosOnly.addEventListener('change', render);
els.verOcultos.addEventListener('change', render);
els.refreshBtn.addEventListener('click', fetchResults);

initCollapsible('configCollapsible', els.toggleConfigBtn, 'radar_config_expanded', false);
initCollapsible('filtersCollapsible', els.toggleFiltersBtn, 'radar_filters_expanded', false);
initCollapsible('mapCollapsible', els.toggleMapBtn, 'radar_map_expanded', false, initMapaSeNecessario);

(async () => {
  await fetchConfig();
  await fetchResults();
  pollScrapeStatus();
  pollCheckStatus();
})();
