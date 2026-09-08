# RadarSemFiador

Automação que varre uma busca de arrendamento no [idealista.pt](https://www.idealista.pt) e sinaliza os anúncios que **não exigem fiador** (ou nem mencionam o assunto), poupando o trabalho de abrir um por um.

![Interface do RadarSemFiador](screenshots/ui-top.png)

## Como funciona

A aplicação roda num **único processo Python** (`app.py`, Flask): ele serve a interface web e, a partir dela, dispara o scraper (Playwright) em segundo plano — sem precisar de um segundo terminal/processo separado como nas versões anteriores.

1. Na interface, defina a **URL de busca** do idealista (ou use a padrão já configurada) e clique em **Executar scraper**.
2. `scraper.py` percorre as páginas de resultados dessa URL. Para cada anúncio novo (não visitado antes, controlado por `data/historico_anuncios.json`), abre a página de detalhe e extrai título, preço e descrição.
3. Classifica o anúncio conforme o texto:
   - **CONFIRMADO (Explícito/Flexível)** — o anúncio diz explicitamente que dispensa fiador, aceita caução reforçada, etc.
   - **SEM MENÇÃO** — a palavra "fiador" nem aparece no texto.
   - **EXIGE FIADOR** — o texto menciona fiador como exigência.
   - **BLOQUEADO_POR_ANTI_BOT** — a página caiu em proteção anti-bot (Cloudflare, captcha, etc.) e não pôde ser lida.
4. Salva tudo em `data/resultados_idealista.json`.
5. A interface consome esses dados via API (`/api/results`), com filtros por status, tipologia, tipo de anunciante e **favoritos**.

## Arquitetura

```
app.py            -> processo único: serve a UI (static/) e expõe a API REST
scrape_runner.py  -> executa scraper.py numa thread em segundo plano (não bloqueia a UI)
scraper.py        -> lógica de scraping com Playwright (funções puras + navegação)
storage.py        -> toda a persistência em JSON (config, favoritos, resultados, histórico, log)
static/           -> interface (index.html, app.js, styles.css)
data/             -> ficheiros gerados em runtime (não versionados)
tests/            -> testes unitários e de integração (pytest)
```

### API

| Método | Rota                     | Descrição                                                             |
|--------|---------------------------|-------------------------------------------------------------------------|
| GET    | `/`                        | Interface web                                                          |
| GET    | `/api/results`             | Resultados da última varredura, com flag `favorito`                    |
| GET    | `/api/config`               | URL padrão e URL atual configuradas                                    |
| POST   | `/api/config`               | Atualiza a URL atual (`{"url": "..."}`); a URL padrão nunca é perdida  |
| POST   | `/api/config/reset`         | Restaura a URL atual para a padrão                                     |
| GET    | `/api/favorites`            | Lista de links favoritados                                             |
| POST   | `/api/favorites/toggle`     | Alterna favorito (`{"link": "..."}`)                                   |
| GET    | `/api/scrape/status`        | Estado da execução em curso (`idle`/`running`/`done`/`error`)          |
| POST   | `/api/scrape`               | Dispara uma nova execução do scraper com a URL atual configurada       |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
playwright install chromium
```

## Uso

```bash
python app.py
```

Abra `http://127.0.0.1:8000/`. Na interface:

- **Configuração da busca**: ajuste a "URL atual" (localização, preço, tipologia, etc. — cole aqui a URL de uma busca no idealista.pt) e clique em **Guardar URL**. A "URL padrão" nunca é sobrescrita; use **Restaurar padrão** para voltar a ela a qualquer momento.
- **Executar scraper**: dispara a varredura com a URL atual configurada. O botão fica desativado enquanto a execução está em curso e a interface faz polling do estado (`/api/scrape/status`) até concluir, recarregando os resultados automaticamente.
- **Favoritar**: cada anúncio tem um botão ★/☆ para marcar/desmarcar como favorito. Use o filtro "Somente favoritos" para ver só os marcados.

Os arquivos gerados (`historico_anuncios.json`, `resultados_idealista.json`, `config.json`, `favoritos.json`, `scraper_log.txt`) ficam em `data/` e não são versionados.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

- `tests/unit/test_scraper_parsing.py` — funções puras de classificação de texto (fiador, tipologia, tipo de anunciante, bloqueio anti-bot).
- `tests/unit/test_storage.py` — persistência de histórico, resultados, configuração e favoritos, isolada em pastas temporárias.
- `tests/unit/test_scrape_runner.py` — orquestração da execução em segundo plano (sucesso, erro, e bloqueio de execuções concorrentes), usando um coroutine falso no lugar do Playwright real.
- `tests/integration/test_api.py` — todas as rotas da API Flask via test client, incluindo o fluxo completo de configurar URL, favoritar e disparar/concluir um scrape simulado.

## Notas

- O navegador do scraper roda em modo visível (`headless=False` por padrão) e com atrasos aleatórios entre páginas/anúncios para reduzir a chance de bloqueio por anti-bot.
- A URL configurada é validada para começar com `https://www.idealista.pt`, já que os seletores do scraper são específicos desse site.
- Projeto pessoal para uso educacional — respeite os termos de uso do idealista e evite varreduras agressivas.

## Licença

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — veja [LICENSE](LICENSE). Livre pra uso não-comercial; me procure pra qualquer uso comercial.
