# COT Monitor — Седмичен наратив за пазарните позиции

Дашборд за **контекст върху позиционирането** на 38 фючърсни пазара (акции, облигации, валути, метали, енергоносители, агрокултури), базиран на седмичния CFTC Commitments of Traders отчет.

> **Не е инвестиционен съвет.** Това е аналитичен инструмент за разбиране на пазарната структура — не дава сигнали за покупка/продажба, не предсказва пазара и не е база за вземане на решения.

## Какво показва

- **Тази седмица** — авто-генериран наратив с топ движения, екстремуми и многоседмични трендове
- **Секторна картина** — агрегирано спекулативно позициониране по сектори (акции, облигации, валути, метали, енергия, агро)
- **Пълен преглед** — таблица с всички 38 пазара, sortable; кликни ред за разбивка по групи играчи (Спекулативни / Институционални / Производители / Дилъри / Суап дилъри)
- **Какво НЕ виждаме** — методология и ограничения (закъснение на CFTC данните, какво физически липсва, как да се чете перцентилът)

## Покрит universe (38 пазара)

| Сектор | Пазари |
|---|---|
| Американски акции (3) | S&P 500, Nasdaq 100, Russell 2000 |
| US облигации (5) | UST 2Y, 5Y, 10Y, Ultra 10Y, 30Y |
| Волатилност (1) | VIX |
| G10 валути (7) | EUR, GBP, JPY, CHF, CAD, AUD, DXY |
| Криптовалути (1) | Bitcoin |
| Метали (5) | Злато, Сребро, Мед, Платина, Паладий |
| Енергоносители (5) | WTI, Brent, Природен газ (Henry Hub), RBOB бензин, Дизел (NY Harbor ULSD) |
| Зърнени (5) | Царевица, Соя, Пшеница (SRW), Соево олио, Соев шрот |
| Soft commodities (4) | Кафе, Захар, Какао, Памук |
| Животновъдство (2) | Едър рогат добитък, Свине |

## Технически детайли

- **Източник на данни:** [CFTC Public Reporting API](https://publicreporting.cftc.gov/) (TFF + Disaggregated отчети)
- **Цени:** Yahoo Finance (10-годишни дневни редове)
- **Период на следене:** до 10 години седмични данни (520 наблюдения), с **incremental cache** — историята се натрупва постепенно
- **Обновяване:** автоматично всеки петък 21:00 UTC (след CFTC публикацията 15:30 ET) чрез GitHub Actions
- **Hosting:** статичен HTML на GitHub Pages, без backend

## Структура

```
cot-monitor/
├── index.html                 # БГ narrative dashboard
├── data/
│   ├── manifest.json          # Списък markets и метаданни
│   ├── markets/*.json         # Per-market COT + price history (38 файла)
│   ├── derived/
│   │   ├── watchlist.json     # Score + regime + percentile + streak per market
│   │   ├── weekly_changes.json
│   │   └── narratives.json
│   ├── cta_model/             # TSMOM signals (опционални, не се ползват в наратива)
│   └── ai_context.json
├── scripts/
│   ├── fetch_cot.py           # CFTC API + Yahoo + incremental merge
│   ├── derive_metrics.py      # Z-scores, percentiles, streaks
│   ├── cta_model.py           # TSMOM ensemble signals
│   ├── generate_ai_context.py
│   └── discover_cftc_names.py # Diagnostic за CFTC name patterns
├── docs/
│   ├── methodology.md
│   └── github-pages-setup.md
└── .github/workflows/weekly-refresh.yml
```

## Локално стартиране

```bash
# Инсталация
pip install -r requirements.txt

# Refresh на данните (опционално — има vendored copy)
python scripts/fetch_cot.py
python scripts/derive_metrics.py
python scripts/cta_model.py
python scripts/generate_ai_context.py

# Стартирай локален server
python -m http.server 8000
# Отвори http://localhost:8000
```

## Лиценз и източници

Данните са от CFTC (публични). Кодът е MIT. Дашбордът няма гаранции за точност на интерпретацията.

Първоначалното имплементиране и продуктовият дизайн произхождат от експерименти с
[cot-cta-positioning-dashboard](https://github.com/tsvetoslavtsachev/cot-cta-positioning-dashboard) — техническата база остана,
наративният layer и БГ-преводите са изградени специално за това repo.
