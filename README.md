# RadarSemFiador

Automação que varre buscas de arrendamento em múltiplos sites — hoje [idealista.pt](https://www.idealista.pt) e [Imovirtual](https://www.imovirtual.com) — e sinaliza os anúncios que **não exigem fiador** (ou nem mencionam o assunto), poupando o trabalho de abrir um por um.

![Interface do RadarSemFiador](screenshots/ui-top.png)

## Como funciona

A aplicação roda num **único processo Python** (`app.py`, Flask): ele serve a interface web e, a partir dela, dispara os scrapers (Playwright) em segundo plano — cada fonte com o seu próprio botão "Executar scraper", sem precisar de terminais separados.

1. Na interface, cada fonte tem o seu próprio painel de **configuração da busca** — defina a URL (ou use a padrão já configurada) e clique em **Executar scraper**.
2. O scraper daquela fonte percorre as páginas de resultados dessa URL. Para cada anúncio novo (não visitado antes — o histórico é partilhado entre fontes, em `data/historico_anuncios.json`), abre a página de detalhe e extrai título, preço, descrição, tipologia, tipo de anunciante e data de atualização.
3. Classifica o anúncio conforme o texto (lógica comum a todas as fontes, em `classificacao.py`):
   - **CONFIRMADO (Explícito/Flexível)** — o anúncio diz explicitamente que dispensa fiador, aceita caução reforçada, etc.
   - **SEM MENÇÃO** — a palavra "fiador" nem aparece no texto.
   - **EXIGE FIADOR** — o texto menciona fiador como exigência.
   - **BLOQUEADO_POR_ANTI_BOT** / **ERRO_TEXTO_VAZIO** — a página não pôde ser lida corretamente (proteção anti-bot, página vazia, etc.); a interface mostra esses casos com um aviso visual em vez de misturá-los com classificações reais.
4. Salva cada anúncio (com a **descrição completa**, não só um trecho) no ficheiro daquela fonte assim que ele é classificado — não espera a varredura inteira terminar. Se o processo for interrompido no meio, o que já foi analisado não se perde. A gravação mescla com o que já existia (uma varredura nunca revisita um anúncio já visto, então precisa preservar os anteriores em vez de sobrescrever).
5. A interface combina os resultados de todas as fontes via API (`/api/results`), com filtros por **fonte**, status, tipologia, tipo de anunciante, **faixa de preço** e **favoritos**, além de ordenação por data de atualização.

## Arquitetura

```
app.py                    -> processo único: serve a UI (static/) e expõe a API REST
scrape_runner.py          -> um ScrapeJobManager por fonte, cada um numa thread em segundo plano
classificacao.py          -> classificação de fiador e extração de tipologia/anunciante, comum a todas as fontes
scraper.py                -> scraper do idealista.pt (navegação + extração específica do site)
scraper_imovirtual.py     -> scraper do Imovirtual (navegação + extração específica do site)
storage.py                -> persistência em JSON (config e resultados por fonte; histórico e favoritos partilhados)
static/                   -> interface (index.html, app.js, styles.css)
data/                     -> ficheiros gerados em runtime (não versionados)
tests/                    -> testes unitários e de integração (pytest)
```

Adicionar uma nova fonte (ex.: OLX) significa: uma entrada em `storage.FONTES`, um módulo `scraper_olx.py` reaproveitando `classificacao.py`, e uma entrada em `scrape_runner.criar_job_managers_padrao` — a API e a interface já são genéricas por fonte e não precisam de mudanças estruturais.

### API

| Método | Rota                          | Descrição                                                                |
|--------|--------------------------------|---------------------------------------------------------------------------|
| GET    | `/`                             | Interface web                                                            |
| GET    | `/api/results`                  | Resultados de todas as fontes combinados, cada item com `fonte` e `favorito` |
| GET    | `/api/config`                   | Config (URL padrão/atual) de cada fonte                                  |
| POST   | `/api/config/<fonte>`           | Atualiza a URL atual daquela fonte (`{"url": "..."}`); a padrão nunca é perdida |
| POST   | `/api/config/<fonte>/reset`     | Restaura a URL atual daquela fonte para a padrão                         |
| GET    | `/api/favorites`                | Lista de links favoritados                                               |
| POST   | `/api/favorites/toggle`         | Alterna favorito (`{"link": "..."}`)                                     |
| GET    | `/api/scrape/status`            | Estado de execução de cada fonte (`idle`/`running`/`done`/`error`)       |
| POST   | `/api/scrape/<fonte>`           | Dispara uma execução daquela fonte com a URL atual configurada           |

`<fonte>` é `idealista` ou `imovirtual`.

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

- **Configuração da busca** (um painel por fonte): ajuste a "URL atual" (localização, preço, tipologia, etc.) e clique em **Guardar URL**. A "URL padrão" nunca é sobrescrita; use **Restaurar padrão** para voltar a ela a qualquer momento.
- **Executar scraper**: dispara a varredura daquela fonte com a URL atual configurada. Fontes diferentes podem rodar ao mesmo tempo sem interferir uma na outra; só não é possível disparar duas execuções da *mesma* fonte simultaneamente. O botão fica desativado enquanto a execução está em curso, uma barra de progresso mostra quantos anúncios já foram analisados frente ao total encontrado (com uma estimativa de tempo restante, calculada pelo ritmo real da execução), e a interface recarrega os resultados automaticamente ao concluir.
- **Buscar**: filtra por palavra-chave no título, na descrição completa ou no trecho decisivo do fiador.
- **Fonte**: filtra os resultados por site de origem.
- **Preço**: filtra por faixa mínima/máxima em euros.
- **Favoritar**: cada anúncio tem um botão ★/☆ para marcar/desmarcar como favorito. Use o filtro "Somente favoritos" para ver só os marcados.
- **Descrição**: aparece resumida (4 linhas); clique nela para expandir/recolher o texto completo.
- **Ordenar por**: escolha "Data de atualização (mais recente)" ou "(mais antiga)" para reordenar os cards; anúncios sem data identificada ficam sempre no fim da lista.

Os arquivos gerados (`historico_anuncios.json`, `resultados_idealista.json`, `resultados_imovirtual.json`, `config.json`, `favoritos.json`, `scraper_log.txt`) ficam em `data/` e não são versionados.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

- `tests/unit/test_classificacao.py` — classificação de fiador (comum a todas as fontes): confirmação explícita, negações, bloqueio anti-bot.
- `tests/unit/test_scraper_parsing.py` — extração específica do idealista (data de atualização a partir do texto "Anúncio atualizado no dia...").
- `tests/unit/test_scraper_playwright_helpers.py` — extratores assíncronos do idealista que dependem de uma `page` (com um dublê no lugar do Playwright real).
- `tests/unit/test_scraper_imovirtual_parsing.py` — extração específica do Imovirtual: paginação (`page=N`, incluindo o caso em que o site "clampa" para a última página existente), data de atualização (formato `D.MM.AAAA`, já com ano), parsing do JSON-LD estruturado, e a normalização de links promovidos (`/hpr/...`) que apontam pro mesmo anúncio.
- `tests/unit/test_storage.py` — persistência por fonte (resultados, config) e partilhada (histórico, favoritos), incluindo a migração automática do formato antigo de `config.json`.
- `tests/unit/test_scrape_runner.py` — orquestração da execução em segundo plano por fonte: sucesso, erro, progresso e ETA reportados durante a execução, bloqueio de execuções concorrentes da mesma fonte, e independência entre fontes diferentes.
- `tests/integration/test_api.py` — todas as rotas da API Flask via test client, incluindo o fluxo completo por fonte.

## Notas

- O navegador dos scrapers roda em modo visível (`headless=False` por padrão) e com atrasos aleatórios entre páginas/anúncios para reduzir a chance de bloqueio por anti-bot — o mesmo princípio aplicado a todas as fontes.
- Cada fonte só aceita URLs do seu próprio domínio (validado em `/api/config/<fonte>`), já que os seletores de cada scraper são específicos daquele site.
- O Imovirtual expõe tipologia, tipo de anunciante, preço e descrição de forma estruturada (JSON-LD), o que torna a extração mais confiável do que a do idealista, que depende mais de heurísticas sobre texto livre.
- Tudo que os scrapers fazem (páginas visitadas, classificação de cada anúncio, erros) é gravado em `data/scraper_log.txt`, além de aparecer no terminal — é o primeiro lugar a olhar se algo parecer errado numa execução.
- A página de detalhe do Imovirtual só espera o carregamento inicial do HTML (`domcontentloaded`) em vez de esperar a rede ficar ociosa (`networkidle`): medido em execução real, ~18% das páginas nunca atingiam esse estado (anúncios/scripts mantêm requisições em segundo plano) e expiravam no timeout de 20s à toa — os dados usados (JSON-LD) já vêm prontos no HTML inicial.
- A descrição completa de cada anúncio é guardada (não só um trecho), permitindo a busca por palavra-chave no conteúdo. Anúncios já visitados em execuções antigas (antes dessa mudança) mantêm a descrição truncada de 250 caracteres que foi salva na época, já que o histórico impede revisitá-los; só uma nova execução sobre eles (ex.: limpando `historico_anuncios.json`) atualizaria para o texto completo.
- Projeto pessoal para uso educacional — respeite os termos de uso de cada site e evite varreduras agressivas.

## Licença

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — veja [LICENSE](LICENSE). Livre pra uso não-comercial; me procure pra qualquer uso comercial.
