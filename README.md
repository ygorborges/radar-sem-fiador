# RadarSemFiador

Automação que varre uma busca de arrendamento no [idealista.pt](https://www.idealista.pt) e sinaliza os anúncios que **não exigem fiador** (ou nem mencionam o assunto), poupando o trabalho de abrir um por um.

## Como funciona

1. `scraper.py` usa [Playwright](https://playwright.dev/python/) para percorrer as páginas de resultados de uma URL de busca do idealista.
2. Para cada anúncio novo (não visitado antes, controlado por `data/historico_anuncios.json`), abre a página de detalhe e extrai título, preço e descrição.
3. Classifica o anúncio conforme o texto:
   - **CONFIRMADO (Explícito/Flexível)** — o anúncio diz explicitamente que dispensa fiador, aceita caução reforçada, etc.
   - **SEM MENÇÃO** — a palavra "fiador" nem aparece no texto.
   - **EXIGE FIADOR** — o texto menciona fiador como exigência.
   - **BLOQUEADO_POR_ANTI_BOT** — a página caiu em proteção anti-bot (Cloudflare, captcha, etc.) e não pôde ser lida.
4. Salva tudo em `data/resultados_idealista.json`.
5. `serve_ui.py` sobe um servidor local simples para visualizar os resultados em `index.html`, com filtros por status, tipologia e tipo de anunciante.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
playwright install chromium
```

## Uso

1. Ajuste `URL_BASE_DEFAULT` em [scraper.py](scraper.py) com a URL da sua busca no idealista (localização, preço, tipologia, etc.).
2. Rode a varredura:
   ```bash
   python scraper.py
   ```
3. Suba o painel de resultados:
   ```bash
   python serve_ui.py
   ```
   e abra `http://127.0.0.1:8000/index.html`.

Os arquivos gerados (`historico_anuncios.json`, `resultados_idealista.json`, `scraper_log.txt`) ficam em `data/` e não são versionados.

## Notas

- O navegador roda em modo visível (`headless=False`) e com atrasos aleatórios entre páginas/anúncios para reduzir a chance de bloqueio por anti-bot.
- Projeto pessoal para uso educacional — respeite os termos de uso do idealista e evite varreduras agressivas.

## Licença

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — veja [LICENSE](LICENSE). Livre pra uso não-comercial; me procure pra qualquer uso comercial.
