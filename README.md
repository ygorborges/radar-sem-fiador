# RadarArrendamento

Automação que varre buscas de arrendamento em múltiplos sites — hoje [idealista.pt](https://www.idealista.pt) e [Imovirtual](https://www.imovirtual.com) — e sinaliza os anúncios que **não exigem fiador** (ou nem mencionam o assunto), poupando o trabalho de abrir um por um.

Esse continua sendo o foco principal por enquanto, mas o projeto já filtra bem além disso — preço, tipologia, tipo de anunciante, favoritos — e a ideia é crescer como um radar mais geral de imóveis. A visão de médio prazo inclui também a compra de imóveis, com o mesmo espírito: sinalizar ciladas comuns (imóveis devolutos, pendências judiciais, "oportunidades de investimento" duvidosas) em vez de deixar isso para o comprador descobrir sozinho.

![Interface do RadarArrendamento](screenshots/ui-top.png)

## Como funciona

A aplicação roda num **único processo Python** (`app.py`, Flask): ele serve a interface web e, a partir dela, dispara os scrapers (Playwright) em segundo plano — cada fonte com o seu próprio botão "Executar scraper", sem precisar de terminais separados.

1. Na interface, cada fonte tem o seu próprio painel de **configuração da busca** — defina a URL (ou use a padrão já configurada) e clique em **Executar scraper**.
2. O scraper daquela fonte percorre as páginas de resultados dessa URL. Para cada anúncio novo (não visitado antes — o histórico é partilhado entre fontes, em `data/historico_anuncios.json`), abre a página de detalhe e extrai título, preço, descrição, tipologia, tipo de anunciante e data de atualização.
3. Classifica o anúncio conforme o texto (lógica comum a todas as fontes, em `classificacao.py`):
   - **CONFIRMADO (Explícito/Flexível)** — o anúncio diz explicitamente que dispensa fiador, aceita caução reforçada, etc.
   - **SEM MENÇÃO** — a palavra "fiador" nem aparece no texto.
   - **EXIGE FIADOR** — o texto menciona fiador como exigência.
   - **BLOQUEADO_POR_ANTI_BOT** / **ERRO_TEXTO_VAZIO** — a página não pôde ser lida corretamente (proteção anti-bot, página vazia, etc.); a interface mostra esses casos com um aviso visual em vez de misturá-los com classificações reais.
4. Também extrai a **localização** do anúncio, pra exibir no mapa: o Imovirtual já publica coordenadas prontas no JSON-LD da página; o idealista só expõe uma hierarquia de texto (rua, bairro, zona, cidade), sem coordenada — nesse caso, o nível mais específico disponível é geocodificado via Nominatim/OpenStreetMap (`geolocalizacao.py`). Quando só há bairro/zona (sem rua), a localização fica marcada como aproximada.
5. Salva cada anúncio (com a **descrição completa**, não só um trecho) no ficheiro daquela fonte assim que ele é classificado — não espera a varredura inteira terminar. Se o processo for interrompido no meio, o que já foi analisado não se perde. A gravação mescla com o que já existia (uma varredura nunca revisita um anúncio já visto, então precisa preservar os anteriores em vez de sobrescrever).
6. A interface combina os resultados de todas as fontes via API (`/api/results`), com filtros por **fonte**, status, tipologia, tipo de anunciante, **faixa de preço** e **favoritos**, além de ordenação por data de atualização — e um **mapa** que reflete os anúncios filtrados em tempo real.

## Arquitetura

```
app.py                    -> processo único: serve a UI (static/) e expõe a API REST
scrape_runner.py          -> um ScrapeJobManager/VerificacaoJobManager por fonte, cada um numa thread em segundo plano
classificacao.py          -> classificação de fiador e extração de tipologia/anunciante, comum a todas as fontes
scraper.py                -> scraper do idealista.pt (navegação + extração específica do site)
scraper_imovirtual.py     -> scraper do Imovirtual (navegação + extração específica do site)
verificador_disponibilidade.py -> revisita anúncios já coletados: remove os que saíram do ar e preenche localização/descrição que faltem
geolocalizacao.py         -> geocodificação (Nominatim/OpenStreetMap) usada só pelo idealista, com cache em disco
divisoes_administrativas.py -> concelho/freguesia oficiais de Portugal (concelhos_freguesias.json), fonte confiável pro concelho de cada anúncio
storage.py                -> persistência em JSON (config e resultados por fonte; histórico, favoritos e ocultos partilhados)
static/                   -> interface (index.html, app.js, styles.css)
data/                     -> ficheiros gerados em runtime (não versionados)
tests/                    -> testes unitários e de integração (pytest)

scripts/                       -> scripts de manutenção (ver abaixo)
scripts/reclassificar.py           -> reaplica a classificação de fiador aos anúncios já guardados (sem reabrir páginas)
scripts/corrigir_concelhos.py      -> corrige concelho/freguesia dos anúncios já guardados via divisoes_administrativas
scripts/corrigir_geocodificacao.py -> re-geocodifica o idealista com busca estruturada (rua + cidade), usando o concelho já corrigido
```

Os três scripts em `scripts/` existem porque a descrição completa e a localização de cada anúncio já ficam guardadas — sempre que a lógica de classificação/localização é corrigida, dá pra reaplicá-la sobre o que já está em `data/` sem depender de uma nova varredura. Rode-os a partir da raiz do projeto com `python scripts/<script>.py`.

Adicionar uma nova fonte (ex.: OLX) significa: uma entrada em `storage.FONTES`, um módulo `scraper_olx.py` reaproveitando `classificacao.py`, e uma entrada em `scrape_runner.criar_job_managers_padrao` — a API e a interface já são genéricas por fonte e não precisam de mudanças estruturais.

### API

| Método | Rota                          | Descrição                                                                |
|--------|--------------------------------|---------------------------------------------------------------------------|
| GET    | `/`                             | Interface web                                                            |
| GET    | `/api/results`                  | Resultados de todas as fontes combinados, cada item com `fonte`, `favorito`, `oculto` e `localizacao` (quando identificada) |
| GET    | `/api/config`                   | Config (URL padrão/atual) de cada fonte                                  |
| POST   | `/api/config/<fonte>`           | Atualiza a URL atual daquela fonte (`{"url": "..."}`); a padrão nunca é perdida |
| POST   | `/api/config/<fonte>/reset`     | Restaura a URL atual daquela fonte para a padrão                         |
| GET    | `/api/favorites`                | Lista de links favoritados                                               |
| POST   | `/api/favorites/toggle`         | Alterna favorito (`{"link": "..."}`)                                     |
| GET    | `/api/hidden`                   | Lista de links ocultados                                                 |
| POST   | `/api/hidden/toggle`            | Alterna ocultar/mostrar (`{"link": "..."}`)                              |
| GET    | `/api/scrape/status`            | Estado de execução de cada fonte (`idle`/`running`/`done`/`error`)       |
| POST   | `/api/scrape/<fonte>`           | Dispara uma execução daquela fonte com a URL atual configurada           |
| GET    | `/api/check/status`             | Estado da verificação de disponibilidade de cada fonte                  |
| POST   | `/api/check/<fonte>`            | Dispara a verificação daquela fonte (remove anúncios fora do ar, preenche localização em falta) |

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

Abra `http://127.0.0.1:8000/`. O cabeçalho tem três botões que mostram/escondem as respectivas seções (o estado de cada um fica salvo no navegador):

- **Configurações de busca** (um painel por fonte): ajuste a "URL atual" (localização, preço, tipologia, etc.) e clique em **Guardar URL**. A "URL padrão" nunca é sobrescrita; use **Restaurar padrão** para voltar a ela a qualquer momento.
  - **Executar scraper**: dispara a varredura daquela fonte com a URL atual configurada. Fontes diferentes podem rodar ao mesmo tempo sem interferir uma na outra; só não é possível disparar duas execuções da *mesma* fonte simultaneamente. O botão fica desativado enquanto a execução está em curso, uma barra de progresso mostra quantos anúncios já foram analisados frente ao total encontrado (com uma estimativa de tempo restante, calculada pelo ritmo real da execução), e a interface recarrega os resultados automaticamente ao concluir.
  - **Verificar anúncios ativos**: revisita os anúncios já coletados daquela fonte e **remove definitivamente** da lista os que já saíram do ar (arrendados ou removidos pelo anunciante) — aproveitando a mesma visita, também preenche a localização de anúncios que ainda não têm. Mesmo modelo de progresso/estado da varredura.
- **Filtros**: busca por palavra-chave (título, descrição completa ou trecho decisivo do fiador), fonte, status de fiador, tipologia, tipo de anunciante, faixa de preço e ordenação por data de atualização. **Favoritar** (★/☆) e **Ocultar** (🙈) ficam em cada card — "Somente favoritos" e "Ver ocultos" filtram por eles; ocultar só tira da vista (não apaga nada), então "Ver ocultos" serve pra rever/desocultar depois.
- **Concelho** e **Freguesia**: filtro hierárquico — a lista de freguesias muda conforme o concelho escolhido (mostra só as daquele concelho; com "Todos" selecionado, mostra todas). Depende da localização identificada em cada anúncio (ver "Notas"); sem ela, o anúncio fica de fora quando um desses filtros está ativo.
- **Mapa**: mostra num mapa (Leaflet/OpenStreetMap) os anúncios que estão passando pelos filtros no momento — atualiza sozinho a cada mudança de filtro. Um marcador de pino indica endereço preciso; um círculo translúcido indica que só a região é conhecida (o anunciante não revelou a rua). Anúncios sem localização identificada não aparecem, mas continuam na lista normalmente — rode **Verificar anúncios ativos** para preencher a localização dos que faltam.
- **Descrição**: aparece resumida (4 linhas); clique nela para expandir/recolher o texto completo.

Os arquivos gerados (`historico_anuncios.json`, `resultados_idealista.json`, `resultados_imovirtual.json`, `config.json`, `favoritos.json`, `ocultos.json`, `geocode_cache.json`, `scraper_log.txt`) ficam em `data/` e não são versionados.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

- `tests/unit/test_classificacao.py` — classificação de fiador (comum a todas as fontes): confirmação explícita, negações, bloqueio anti-bot.
- `tests/unit/test_scraper_parsing.py` — extração específica do idealista (data de atualização a partir do texto "Anúncio atualizado no dia...").
- `tests/unit/test_scraper_playwright_helpers.py` — extratores assíncronos do idealista que dependem de uma `page` (com um dublê no lugar do Playwright real).
- `tests/unit/test_scraper_imovirtual_parsing.py` — extração específica do Imovirtual: paginação (`page=N`, incluindo o caso em que o site "clampa" para a última página existente), data de atualização (formato `D.MM.AAAA`, já com ano), parsing do JSON-LD estruturado, e a normalização de links promovidos (`/hpr/...`) que apontam pro mesmo anúncio.
- `tests/unit/test_storage.py` — persistência por fonte (resultados, config) e partilhada (histórico, favoritos, ocultos, cache de geocodificação), incluindo a migração automática do formato antigo de `config.json`.
- `tests/unit/test_geolocalizacao.py` — geocodificação via Nominatim (busca livre e estruturada, sem resultado, falha de rede) e o cache em disco, com a chamada HTTP sempre substituída por um dublê (nunca bate na rede de verdade).
- `tests/unit/test_divisoes_administrativas.py` — concelho a partir da freguesia (formatos diferentes entre fontes, paróquias antigas, nomes ambíguos entre concelhos, desempate por dica de cidade).
- `tests/unit/test_verificador_disponibilidade.py` — decisão de disponibilidade a partir de status HTTP/texto da página.
- `tests/unit/test_reclassificar.py`, `test_corrigir_concelhos.py`, `test_corrigir_geocodificacao.py` — os scripts de manutenção que reaplicam classificação/localização aos anúncios já guardados.
- `tests/unit/test_scrape_runner.py` — orquestração da execução em segundo plano por fonte: sucesso, erro, progresso e ETA reportados durante a execução, bloqueio de execuções concorrentes da mesma fonte, e independência entre fontes diferentes.
- `tests/integration/test_api.py` — todas as rotas da API Flask via test client, incluindo o fluxo completo por fonte.

## Notas

- O navegador dos scrapers roda em modo visível (`headless=False` por padrão) e com atrasos aleatórios entre páginas/anúncios para reduzir a chance de bloqueio por anti-bot — o mesmo princípio aplicado a todas as fontes.
- Cada fonte só aceita URLs do seu próprio domínio (validado em `/api/config/<fonte>`), já que os seletores de cada scraper são específicos daquele site.
- O Imovirtual expõe tipologia, tipo de anunciante, preço e descrição de forma estruturada (JSON-LD), o que torna a extração mais confiável do que a do idealista, que depende mais de heurísticas sobre texto livre.
- Tudo que os scrapers fazem (páginas visitadas, classificação de cada anúncio, erros) é gravado em `data/scraper_log.txt`, além de aparecer no terminal — é o primeiro lugar a olhar se algo parecer errado numa execução.
- A página de detalhe do Imovirtual só espera o carregamento inicial do HTML (`domcontentloaded`) em vez de esperar a rede ficar ociosa (`networkidle`): medido em execução real, ~18% das páginas nunca atingiam esse estado (anúncios/scripts mantêm requisições em segundo plano) e expiravam no timeout de 20s à toa — os dados usados (JSON-LD) já vêm prontos no HTML inicial.
- A descrição completa de cada anúncio é guardada (não só um trecho), permitindo a busca por palavra-chave no conteúdo. Anúncios já visitados em execuções antigas (antes dessa mudança) mantêm a descrição truncada de 250 caracteres que foi salva na época, já que o histórico impede revisitá-los; só uma nova execução sobre eles (ex.: limpando `historico_anuncios.json`) atualizaria para o texto completo.
- A geocodificação (idealista) usa a API pública da Nominatim, que limita a 1 pedido por segundo e exige um User-Agent identificável — ambos respeitados em `geolocalizacao.py`. O cache em `data/geocode_cache.json` evita repetir pedidos pro mesmo endereço/bairro entre execuções. Quando o concelho já foi confirmado, usa busca **estruturada** (`street`+`city` separados) — mas isso sozinho não bastou: nomes de rua/praça comuns em Portugal ("Praça da República" existe em dezenas de cidades) faziam a Nominatim devolver, às vezes em primeiro lugar, um resultado de *outra* cidade, porque o parâmetro `city` dela também compara com o distrito (que cobre várias cidades) e a ordenação por "importância" do OSM não é confiável pra esse fim. A correção: pedir vários candidatos e só aceitar um cujo `address.city`/`town`/`village`/`municipality` bate exatamente com a cidade pedida — sem isso, devolve `None` em vez de uma coordenada errada.
- Anúncios coletados antes da funcionalidade de mapa (ou do filtro de concelho/freguesia) existir não têm esses campos até serem revisitados — rode **Verificar anúncios ativos** de cada fonte pra preencher/completar os que faltam (ela aproveita a própria visita de verificação de disponibilidade pra isso, sem precisar de uma varredura nova, e também completa quem já tinha `localizacao` num formato mais antigo).
- **O concelho de cada anúncio nunca vem direto do site** — `addressRegion` do Imovirtual é o *distrito* (ex.: "Porto" cobre Porto, Gondomar, Maia, Matosinhos, Valongo, Gaia e mais uma dúzia de concelhos, não só o concelho "Porto"), e o último nível da lista de localização do idealista às vezes junta concelho e distrito numa única string capenga ("Vila Nova de Gaia, Porto"). O concelho é sempre derivado da freguesia (essa sim, relativamente confiável nos dois sites) através da divisão administrativa oficial (`divisoes_administrativas.py`, 306 concelhos / 3092 freguesias — pós-reorganização de 2013). Nomes de freguesia se repetem por Portugal mais do que se esperaria (ex.: "Paranhos" existe no Porto e em Seia; "Oliveira do Douro" existe em Gaia e em Cinfães) — nesses casos o concelho fica `None` (não filtrável) a menos que o texto bruto da fonte sirva de desempate; ~7% dos anúncios com localização caem nessa categoria.
- Projeto pessoal para uso educacional — respeite os termos de uso de cada site e evite varreduras agressivas.

## Licença

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — veja [LICENSE](LICENSE). Livre pra uso não-comercial; me procure pra qualquer uso comercial.
