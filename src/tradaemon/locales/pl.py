"""Polish message catalogue — the source language.

Every string here was written first; `en.py` is its translation. When you add a key,
add it to both files: `tests/test_i18n.py` fails otherwise.

Sections follow the modules the strings appear in.
"""

from __future__ import annotations

MESSAGES: dict[str, str] = {

    # ---------- formatting ----------
    "fmt.decimal_separator": ",",
    "fmt.money": "{amount} $",

    # ---------- humanize: why the bot did or did not trade ----------
    "reason.in_position": "trzyma pozycję",
    "reason.warmup": "rozgrzewa się (zbiera dane)",
    "reason.risk_blocked": "widzi okazję, ale limit ryzyka nie pozwala",
    "reason.features_nan": "czeka na komplet danych",
    "reason.no_atr": "czeka na komplet danych",
    "reason.below_threshold": "nie widzi wystarczającej okazji",
    "reason.enter_long": "otwiera pozycję (stawia na wzrost)",
    "reason.enter_short": "otwiera pozycję (stawia na spadek)",

    # ---------- humanize: how a position closed ----------
    "exit.tp": "z zyskiem (cel osiągnięty)",
    "exit.sl": "ze stratą (bezpiecznik)",
    "exit.timeout": "po upływie czasu",

    # ---------- humanize: glossary tooltips ----------
    "glossary.sharpe": "Zysk w stosunku do wahań. Wyżej = lepiej. Powyżej 1 to dobrze, "
                       "poniżej 0 oznacza stratę względem ryzyka.",
    "glossary.max_drawdown": "Największy spadek od szczytu do dołka. -20% znaczy, że w "
                             "najgorszym momencie portfel był o piątą część niżej niż "
                             "na maksimum.",
    "glossary.profit_factor": "Ile zarobiono na każdą 1 $ straty. Powyżej 1 = więcej "
                              "zysków niż strat.",
    "glossary.win_rate": "Odsetek transakcji zakończonych na plusie.",
    "glossary.buy_hold": "Kupujesz raz i nic nie robisz. To poprzeczka: bot ma sens "
                         "tylko, jeśli jest lepszy niż zwykłe trzymanie.",
    "glossary.rebalance": "Przywrócenie zaplanowanych proporcji koszyka (np. z powrotem "
                          "50/30/20), gdy ceny je rozjadą.",
    "glossary.drift": "O ile proporcje koszyka odjechały od planu (w punktach "
                      "procentowych).",
    "glossary.cagr": "Średnioroczne tempo wzrostu — ile procent na rok wychodziłoby "
                     "średnio.",
    "glossary.volatility": "Jak mocno wartość skacze w górę i w dół. Niżej = spokojniej.",
    "glossary.kill_switch": "Bezpiecznik: po zbyt dużej stracie w ciągu dnia bot "
                            "przestaje otwierać nowe pozycje.",
    "glossary.money_at_work": "Jaka część konta naprawdę siedzi w rynku. Reszta czeka "
                              "w gotówce i nic nie robi — ani nie zarabia, ani nie traci.",
    "glossary.return_total": "Wynik policzony od wszystkich pieniędzy — także tych, "
                             "które leżały bezczynnie. Dlatego wygląda łagodniej, niż "
                             "zasługuje sam pomysł bota.",
    "glossary.time_in_market": "Jak często bot w ogóle miał otwartą pozycję. Niski wynik "
                               "znaczy, że przez większość czasu tylko czekał.",
    "glossary.return_at_work": "Ten sam wynik, ale policzony tylko od pieniędzy, które "
                               "faktycznie grały. To uczciwsza ocena samego pomysłu: "
                               "gdyby bot grał całym kontem, wyszłoby mniej więcej tyle. "
                               "Przybliżenie, nie wyrocznia — a gdy bot był w rynku "
                               "bardzo rzadko, pokazujemy „—”, bo przeliczanie takiej "
                               "resztki na całe konto to już zgadywanie.",
    "glossary.bh_fair": "Ktoś, kto włożył w rynek tyle samo pieniędzy co bot i po prostu "
                        "czekał. To sprawiedliwa poprzeczka — porównanie z kimś, kto "
                        "włożył wszystko, chwali bota za samą nieobecność w spadkach.",

    # ---------- humanize: cards ----------
    "card.position.long": "Kupił {asset} za {amount}",
    "card.position.short": "Gra na spadek {asset} za {amount}",
    "card.position.now": "teraz {pnl} ({pct}%)",
    "card.holding.weight": "{weight}% portfela (cel {target}%)",

    # ---------- humanize: event timeline ----------
    "event.trade_closed": "{symbol} zamknięte {how}",
    "event.generic": "zdarzenie",

    # ---------- humanize: status lines ----------
    "status.bot.no_read": "bot jeszcze nie odczytał rynku",
    "status.bot.unknown_time": "nieznany czas ostatniego odczytu",
    "status.bot.running": "działa — ostatnia świeca zamknięta {when}, następna około {next}",
    "status.bot.stale": "może nie odpowiadać — ostatnia świeca zamknięta {when}",
    "status.conn.none": "brak kontaktu z giełdą",
    "status.conn.unknown_time": "nieznany czas kontaktu z giełdą",
    "status.conn.ok": "kontakt z giełdą: {ago}",
    "status.conn.stale": "brak kontaktu z giełdą od {ago} — bot czeka i ponawia",
    "ago.just_now": "przed chwilą",
    "ago.minutes": "{minutes} min temu",
    "ago.hours": "{hours} h {minutes} min temu",
    # ---------- module names, shared by the router and the settings screen ----------
    "module.label": "Moduł",
    "module.crypto": "Krypto-scalper",
    "module.portfolio": "Zarządca portfela",
    "module.research": "Badania",
    "module.settings": "Ustawienia",

    # ---------- settings: sections ----------
    "cfg.section.strategy": "Strategia",
    "cfg.section.risk": "Ryzyko",
    "cfg.section.costs": "Koszty",
    "cfg.section.market": "Rynek i kapitał",
    "cfg.section.training": "Trenowanie",
    "cfg.section.portfolio": "Portfel",
    "cfg.section.changed": "{title} ({n} zmienionych)",

    # ---------- settings: fields ----------
    "cfg.field.strategy.prob_threshold.label": "Próg pewności modelu",
    "cfg.field.strategy.prob_threshold.help": "Minimalne prawdopodobieństwo, przy którym "
        "bot otwiera pozycję. Niżej = więcej transakcji i więcej prowizji.",
    "cfg.field.strategy.tp_atr_mult.label": "Take-profit (× ATR)",
    "cfg.field.strategy.tp_atr_mult.help": "Jak daleko od ceny wejścia ustawiany jest cel "
        "zysku, w jednostkach zmienności (ATR).",
    "cfg.field.strategy.sl_atr_mult.label": "Stop-loss (× ATR)",
    "cfg.field.strategy.sl_atr_mult.help": "Jak daleko ustawiany jest bezpiecznik. Mniej = "
        "szybciej ucina straty, ale częściej wyrzuca z dobrej pozycji.",
    "cfg.field.strategy.horizon_bars.label": "Maksymalny czas trzymania (świece)",
    "cfg.field.strategy.horizon_bars.help": "Po tylu świecach pozycja zamyka się "
        "niezależnie od wyniku.",
    "cfg.field.strategy.rollover.label": "Przedłużanie po terminie",
    "cfg.field.strategy.rollover.help": "Gdy mija maksymalny czas trzymania, a model wciąż "
        "daje sygnał powyżej progu, bot przedłuża pozycję (nowe widełki i termin) zamiast "
        "zamykać i zaraz otwierać ją ponownie za podwójną prowizję.",
    "cfg.field.strategy.atr_period.label": "Okres ATR",
    "cfg.field.strategy.atr_period.help": "Ile świec wstecz liczy się zmienność.",
    "cfg.field.strategy.direction.label": "Kierunek",
    "cfg.field.strategy.direction.help": "long = tylko zakłady na wzrost (zgodne ze "
        "spotem). long_short = także zakłady na spadek; realne shorty wymagają konta "
        "futures.",
    "cfg.field.strategy.warmup_bars.label": "Rozgrzewka (świece)",
    "cfg.field.strategy.warmup_bars.help": "Ile historii bot musi zebrać, zanim policzy "
        "cechy. Zmiana wymaga restartu, bo od tego zależy rozmiar bufora świec.",
    "cfg.field.risk.position_pct.label": "Wielkość pozycji (część kapitału)",
    "cfg.field.risk.position_pct.help": "Jaka część konta idzie w jedną pozycję. "
        "0,10 = 10%.",
    "cfg.field.risk.max_open_positions.label": "Maksimum otwartych pozycji",
    "cfg.field.risk.max_open_positions.help": "Razem z powyższym wyznacza maksymalną "
        "ekspozycję. Pary krypto są mocno skorelowane, więc otwarte pozycje zwykle "
        "zachowują się podobnie. Uwaga: ta zmiana działa niesymetrycznie — w górę wchodzi "
        "już przy najbliższej świecy, w dół dopiero wtedy, gdy nadmiarowe pozycje same się "
        "zamkną.",
    "cfg.field.risk.daily_loss_limit_pct.label": "Dzienny limit straty",
    "cfg.field.risk.daily_loss_limit_pct.help": "Bezpiecznik: po zbyt dużej stracie w ciągu "
        "dnia bot przestaje otwierać nowe pozycje.",
    "cfg.field.risk.drawdown_alert_pct.label": "Próg alertu o obsunięciu",
    "cfg.field.risk.drawdown_alert_pct.help": "Przy jakim spadku od szczytu kapitału panel "
        "ma ostrzegać.",
    "cfg.field.costs.taker_fee.label": "Prowizja taker",
    "cfg.field.costs.taker_fee.help": "Prowizja od zleceń rynkowych. Binance spot domyślnie "
        "0,001 = 0,1%.",
    "cfg.field.costs.maker_fee.label": "Prowizja maker",
    "cfg.field.costs.maker_fee.help": "Prowizja od zleceń limit czekających w księdze.",
    "cfg.field.costs.slippage_bps.label": "Poślizg (punkty bazowe)",
    "cfg.field.costs.slippage_bps.help": "Zakładane niekorzystne odchylenie ceny wykonania. "
        "2 bps = 0,02%.",
    "cfg.field.exchange.timeframe.label": "Interwał świecy",
    "cfg.field.exchange.timeframe.help": "Co ile bot podejmuje decyzję. Zmiana wymaga "
        "restartu i unieważnia model wytrenowany na innym interwale.",
    "cfg.field.exchange.symbols.label": "Pary",
    "cfg.field.exchange.symbols.help": "Lista par oddzielona przecinkami. Model kosztów jest "
        "uczciwy dla par o dużej płynności; cieńsze będą handlować gorzej niż backtest "
        "sugeruje.",
    "cfg.field.paper.initial_capital.label": "Kapitał startowy (paper)",
    "cfg.field.paper.initial_capital.help": "Dotyczy nowych ksiąg. Istniejące księgi trzymają "
        "swój stan w state.json i nie zmienią salda po tej edycji.",
    "cfg.field.primary_variant.label": "Księga na ekranie głównym",
    "cfg.field.primary_variant.help": "Który wariant A/B panel nazywa „Twoim portfelem”.",
    "cfg.field.model.train_window_days.label": "Okno treningowe (dni)",
    "cfg.field.model.train_window_days.help": "Ile historii trafia do treningu. Ustawia też "
        "okno cotygodniowego pobierania danych, więc mała wartość po cichu ogranicza "
        "zbierane dane.",
    "cfg.field.model.validation_days.label": "Okno walidacji (dni)",
    "cfg.field.model.validation_days.help": "Ile dni z końca każdego foldu służy do oceny.",
    "cfg.field.model.n_folds.label": "Liczba foldów",
    "cfg.field.model.n_folds.help": "Ile kroków walidacji kroczącej (walk-forward).",
    "cfg.field.initial_capital.label": "Kapitał startowy",
    "cfg.field.initial_capital.help": "Dotyczy nowej księgi portfela.",
    "cfg.field.rebalance.cadence_days.label": "Rebalans co (dni)",
    "cfg.field.rebalance.cadence_days.help": "Najrzadszy dopuszczalny rytm przywracania "
        "proporcji.",
    "cfg.field.rebalance.drift_threshold_pct.label": "Próg driftu (pkt proc.)",
    "cfg.field.rebalance.drift_threshold_pct.help": "O ile proporcje koszyka odjechały od "
        "planu (w punktach procentowych).",
    "cfg.field.trend.enabled.label": "Filtr trendu",
    "cfg.field.trend.enabled.help": "Gdy włączony, aktywo poniżej swojej średniej trafia do "
        "aktywa bezpiecznego. To premia za ryzyko, nie darmowy obiad.",
    "cfg.field.trend.ma_days.label": "Średnia dla filtru trendu (dni)",
    "cfg.field.trend.ma_days.help": "Klasycznie 200 sesji.",

    # ---------- settings: on/off, buttons, messages ----------
    "cfg.bool.on": "włączony",
    "cfg.bool.off": "wyłączony",
    "cfg.save": "Zapisz",
    "cfg.cancel": "Anuluj",
    "cfg.reset_section": "Przywróć domyślne w „{title}”",
    "cfg.nothing_changed": "Nic się nie zmieniło.",
    "cfg.saved": "Zapisano:\n{changes}",
    "cfg.saved.hot": "⚡ Wchodzi w życie przy najbliższej świecy — bez restartu.",
    "cfg.error.bad_value": "Nie rozumiem wartości pola „{field}”.",
    "cfg.error.no_permission": "Brak uprawnień do zmiany ustawień.",
    "cfg.intro": "Zmiany trafiają do `config.overrides.yaml`. Plik `config.yaml` zostaje "
        "nietknięty jako udokumentowany wzorzec — „przywróć domyślne” po prostu usuwa "
        "nadpisanie.",
    "cfg.markers": "{hot} — wchodzi przy najbliższej świecy · {restart} — wymaga restartu "
        "silnika",
    "cfg.portfolio.daily_loop": "Pętla portfela jest dzienna, więc każda zmiana i tak wchodzi "
        "przy najbliższym przebiegu — nie ma tu hot-reloadu.",

    # ---------- settings: slots ----------
    "cfg.slots.head": "**{book}** · {taken} z {cap} miejsc zajętych",
    "cfg.slots.top_p": " (najwyżej {p})",
    "cfg.slots.queued": "{head}, w kolejce z sygnałem: **{queued}**{top}. Każde miejsce "
        "więcej to jedna pozycja przy najbliższej świecy, po {pct} konta.",
    "cfg.slots.free": "{head} — w kolejce nikt nie czeka, więc podniesienie limitu nic dziś "
        "nie zmieni.",
    "cfg.slots.full": "{head} — książka pełna, ale żadna para nie przekracza progu.",
    "cfg.slots.as_of": "Liczby są z ostatniej świecy każdej księgi.",

    # ---------- settings: engine drift ----------
    "cfg.drift.stuck": "Silnik handluje na innych ustawieniach, niż pokazuje ten ekran — "
        "a świeca, przy której powinien je przyjąć, już minęła.",
    "cfg.drift.row": "- **{book}** · `{field}`: silnik ma **{live}**, na dysku {disk}",
    "cfg.drift.restart_fixes": "Restart silnika wyrówna to na pewno — wróci z tego, co "
        "w pliku.",
    "cfg.drift.pending": "⚡ Silnik przyjmie nowe ustawienia przy najbliższej świecy. "
        "Do tego czasu handluje na poprzednich.",

    # ---------- settings: raising the exposure ceiling ----------
    "cfg.ceiling.title": "Podnosisz sufit ekspozycji",
    "cfg.ceiling.from_to": "Z **{before} konta** na **{after} konta** naraz w rynku.",
    "cfg.ceiling.warning": "Powrót do niższej wartości **nie zamyka niczego** — pozycje "
        "otwarte przy wyższym limicie żyją do celu, bezpiecznika albo terminu. 9.08 limit "
        "podniesiony na pięć godzin zdążył otworzyć cztery pozycje; kosztowały 7 USDT długo "
        "po tym, jak wrócił na swoje miejsce.",
    "cfg.ceiling.save_anyway": "Zapisz mimo to",

    # ---------- settings: restart handshake ----------
    "cfg.restart.title": "Zrestartować silnik?",
    "cfg.restart.startup_only": "Te ustawienia silnik czyta tylko przy starcie:",
    "cfg.restart.explain": "Silnik zapisze stan wszystkich ksiąg i zakończy się czysto. "
        "Kontener podniesie się sam (`restart: unless-stopped`), a otwarte pozycje i gotówka "
        "wrócą ze `state.json`. Poza Dockerem trzeba uruchomić go ręcznie.",
    "cfg.restart.do": "Zrestartuj",
    "cfg.restart.later": "Później",
    "cfg.restart.needed": "Zapisano ustawienia, które silnik czyta tylko przy starcie.",
    "cfg.restart.button": "🔄 Zrestartuj silnik",
    "cfg.restart.sent": "Wysłano prośbę o restart. Silnik zejdzie w ciągu ~10 sekund i wróci "
        "z nowymi ustawieniami.",

    # ---------- settings: change history ----------
    "cfg.history.title": "Historia zmian",
    "cfg.history.empty": "Jeszcze nic nie zmieniano — bot działa na wartościach z "
        "config.yaml.",
    "cfg.history.marked_on_chart": "Te momenty są też zaznaczone przerywaną kreską na "
        "wykresie kapitału, żeby było widać, od kiedy wynik dotyczy innych ustawień.",
    "cfg.history.col.time": "czas",
    "cfg.history.col.field": "pole",
    "cfg.history.col.old": "było",
    "cfg.history.col.new": "jest",
    "cfg.history.col.actor": "kto",

    # ---------- settings: A/B variants ----------
    "cfg.variants.title": "Warianty A/B",
    "cfg.variants.help": "Każdy wiersz to osobna księga handlująca tymi samymi świecami. "
        "Puste pole = wartość z sekcji wyżej. Zmiana listy wymaga restartu.",
    "cfg.variants.save": "Zapisz warianty",
    "cfg.variants.reset": "Przywróć domyślne warianty",
    # ---------- layout switch ----------
    "layout.title": "Układ",
    "layout.auto": "auto",
    "layout.mobile": "telefon",
    "layout.desktop": "komputer",
    "layout.help": "„auto” rozpoznaje urządzenie po przeglądarce. Zmień, jeśli trafiło źle "
        "albo chcesz zobaczyć drugi układ. Można też dopisać do adresu `?layout=telefon`, "
        "żeby zapisać wybór w zakładce.",
    "layout.forced_by_url": "Układ wymuszony parametrem `?layout` w adresie — przełącznik "
        "powyżej jest w tej chwili nieaktywny.",
    "layout.show_rest": "Pokaż pozostałe ({n})",
    # ---------- app shell ----------
    "lang.pl": "PL",
    "lang.en": "EN",
    "app.version": "wersja",
    "app.educational": "projekt edukacyjny · handel na papierze · to nie porada inwestycyjna",
    "panel.analytics": "Analityka",
    "panel.model": "Model",
    "panel.variants": "Warianty",
    "panel.experiments": "Eksperymenty",
    "panel.health": "Zdrowie",

    # ---------- charts ----------
    "chart.series.bot": "Twój portfel",
    "chart.series.bh_all": "Wszystko w rynku",
    "chart.series.bh_fair": "Tyle w rynku co bot",
    "chart.value": "Wartość ($)",
    "chart.time": "Czas",
    "chart.series": "Seria",
    "chart.settings_change": "Zmiana ustawień",
    "chart.fields": "Pola",

    # ---------- beginner screen ----------
    "home.you_have": "Ile masz (wirtualne $)",
    "home.since_start": "{change}% od startu",
    "home.split": "💵 wolne: {free} · 📈 w grze: {invested} (**{pct}% pieniędzy**)  ·  "
        "tryb **paper** (ćwiczebny, nie prawdziwe pieniądze)",
    "home.bot_status": "Status bota",
    "home.kill_switch_on": "🛑 Bezpiecznik dzienny włączony — bot nie otwiera teraz nowych "
        "pozycji.",
    "home.how_it_went": "Jak to szło",
    "home.range": "Zakres",
    "home.range.7d": "7 dni",
    "home.range.30d": "30 dni",
    "home.range.all": "Całość",
    "home.benchmark_explainer": "Obie szare linie to ten sam rynek, kupiony i trzymany. "
        "**Jasna** wkłada w niego wszystkie pieniądze — bot łatwo bije ją w spadkach, ale nie "
        "dlatego, że jest mądry, tylko dlatego, że go tam nie było. **Ciemna** wkłada dokładnie "
        "tyle, ile w danej chwili miał w rynku bot, i to ona jest uczciwym porównaniem. W tym "
        "okresie trzymał w rynku średnio **{avg}% pieniędzy** (teraz: **{now}%**) — im mniej, "
        "tym bliżej ciemna linia leży prostej gotówki i tym dalej od jasnej.",
    "home.not_enough_data": "Za mało danych na wykres — bot dopiero zaczyna zbierać historię.",
    "home.holdings": "Co bot teraz trzyma",
    "home.holdings.empty": "Nic — bot czeka na okazję. 🕊️",
    "home.holdings.click": "Kliknij instrument, aby zobaczyć jego kurs.",
    "home.events": "Dziennik zdarzeń",
    "home.events.click": "Kliknij zdarzenie, aby zobaczyć kurs w tamtym momencie.",
    "home.events.empty": "Jeszcze nic się nie wydarzyło.",

    # ---------- metric labels ----------
    "metric.return_total": "Wynik od wszystkich pieniędzy",
    "metric.return_at_work": "Wynik od pieniędzy w grze",
    "metric.sharpe": "Sharpe",
    "metric.max_drawdown": "Max drawdown",
    "metric.profit_factor": "Profit factor",
    "metric.win_rate": "Win rate",
    "metric.money_at_work": "Pieniądze w grze",
    "metric.time_in_market": "Czas w rynku",
    "metric.kill_switch": "Kill-switch",
    "metric.drawdown": "Drawdown",

    # ---------- table columns ----------
    "col.symbol": "Para",
    "col.trades": "Transakcje",
    "col.win_rate": "Win rate",
    "col.net_pnl": "Wynik netto",
    "col.fees": "Prowizje",
    "col.threshold": "Próg",
    "col.decision": "Decyzja",
    "col.variant": "Wariant",
    "col.equity": "Kapitał",
    "col.max_dd_pct": "Max DD %",
    "col.at_work_pct": "W grze %",
    "col.return_on_risked_pct": "Wynik od tego %",
    "col.win_rate_pct": "Win rate %",

    # ---------- analytics tab ----------
    "analytics.no_trades": "Jeszcze żadnych transakcji.",
    "analytics.per_pair": "Wynik per para",
    "analytics.pnl_distribution": "Rozkład wyników transakcji",
    "analytics.pnl_axis": "PnL (USDT)",
    "analytics.count": "Liczba",
    "analytics.exit_reasons": "Powody wyjścia",

    # ---------- model tab ----------
    "model.why": "Dlaczego bot (nie) handluje",
    "model.why.help": "Prawdopodobieństwo modelu i decyzja dla ostatniej świecy każdej pary. "
        "Wejście, gdy prawdopodobieństwo ≥ próg.",
    "model.no_signals": "Brak sygnałów — silnik jeszcze nie policzył prawdopodobieństw "
        "(do końca okna rozgrzewki).",

    # ---------- variants tab ----------
    "variants.title": "Porównanie wariantów na żywo",
    "variants.none": "Brak wariantów A/B. Dodaj sekcję `variants:` w config.yaml, aby kilka "
        "konfiguracji handlowało równolegle na tych samych danych.",
    "variants.equity_axis": "Kapitał (USDT)",

    # ---------- experiments tab ----------
    "experiments.title": "Dziennik eksperymentów",
    "experiments.help": "Każdy backtest/sweep zapisany raz — żeby nie liczyć wielokrotnie "
        "tego samego.",
    "experiments.empty": "Pusto. Uruchom `python scripts/backtest.py`, aby dodać wpis.",

    # ---------- health tab ----------
    "health.title": "Zdrowie systemu",
    "health.variant": "Wariant: {name}",
    "health.ok": "OK",
    "health.attention": "UWAGA",
    "health.active": "AKTYWNY",
    "health.inactive": "nieaktywny",
    "health.last_state": "Ostatni stan",
    "health.stale_pairs": "[{name}] przeterminowane dane dla: {pairs} (silnik może nie "
        "przetwarzać świec)",
    "health.refresher": "Refresher: {status} @ {when} — {detail}",
    "health.recent_alerts": "Ostatnie alerty",
    "health.no_alerts": "Brak alertów.",

    # ---------- crypto module shell ----------
    "crypto.no_data": "Brak danych — uruchom silnik: `python -m tradaemon.engine`",
    "crypto.your_book": "Twój portfel: **{book}** (pozostałe warianty w Szczegółach)",
    "crypto.details": "🔬 Szczegóły dla dociekliwych",
    "crypto.book_picker": "Księga (wariant)",
    # ---------- portfolio module ----------
    "portfolio.series.bh": "Kup i trzymaj",
    "portfolio.range.1y": "1 rok",
    "portfolio.range.5y": "5 lat",
    "portfolio.range.all": "Całość",
    "portfolio.status.no_data": "brak danych — bot jeszcze nie ruszył",
    "portfolio.status.running": "działa — dane z {when}",
    "portfolio.split": "💵 gotówka: {cash} · 📊 w grze: {invested} (**{pct}% pieniędzy**)  ·  "
        "tryb **paper** (ćwiczebny)",
    "portfolio.chart_explainer": "Niebieska nad szarą = rebalansowanie pomaga vs zwykłe "
        "trzymanie koszyka. Tu porównanie jest uczciwe z natury: obie linie mają w rynku "
        "wszystkie pieniądze.",
    "portfolio.not_enough_data": "Za mało danych na wykres — bot dopiero zaczyna.",
    "portfolio.no_allocation_yet": "Jeszcze nic — bot czeka na pierwszą alokację.",
    "portfolio.weight_vs_target": "Waga teraz vs cel",
    "portfolio.pct_of_portfolio": "% portfela",
    "portfolio.now": "teraz",
    "portfolio.target": "cel",
    "portfolio.worst_drift": "Największe odchylenie od planu (drift): {drift} pkt proc. "
        "(rebalans przy ≥ {threshold} pkt lub co {days} dni).",
    "portfolio.rebalance_history": "Historia rebalansów",
    "portfolio.fees_total": "Łącznie prowizji: {fees}  ·  transakcji: {trades}",
    "portfolio.data_status": "Status danych",
    "portfolio.no_config": "Brak `config/portfolio.yaml` — moduł portfela nie jest "
        "skonfigurowany.",
    "portfolio.no_data": "Brak danych portfela — uruchom silnik: `python -m tradaemon.portfolio`",
    "portfolio.basket": "Koszyk: **{basket}** · rebalans co {days} dni lub przy drift ≥ "
        "{threshold} pkt · filtr trendu: {trend}",
    "panel.allocation": "Alokacja",
    "panel.rebalances": "Rebalanse",

    # ---------- price preview ----------
    "price.no_quotes": "Brak zapisanych notowań tego instrumentu.",
    "price.no_quotes_for_chart": "Brak zapisanych notowań tego instrumentu — nie ma z czego "
        "narysować wykresu.",
    "price.now": "teraz {price}",
    "price.span.24h": "24 h",
    "price.span.7d": "7 dni",
    "price.click_for_chart": "Kliknij, aby zobaczyć wykres kursu.",
    "price.chart_for": "Kurs {symbol}",
    "price.close": "✕ zamknij",
    "price.range": "Zakres kursu",
    "price.range.7d": "7 dni",
    "price.range.30d": "30 dni",
    "price.range.90d": "90 dni",
    "price.too_few_quotes": "Za mało notowań w tym zakresie.",
    "price.rate": "Kurs ($)",
    "price.price": "Cena ($)",
    "price.entry_price": "Cena wejścia ($)",
    "price.this_event": "To zdarzenie",
    "price.bot": "Bot",
    "price.mark.entry": "wejście",
    "price.mark.exit": "wyjście",
    "price.mark.held": "trzyma nadal",
    "price.note.triangles": "Trójkąty to transakcje bota: ▲ kupno, ▼ sprzedaż. ",
    "price.note.circle": "Kółko to pozycja, którą bot **nadal trzyma**. ",
    "price.instrument_change": "Kurs samego instrumentu: **{change}%** w wybranym zakresie "
        "(to nie jest wynik bota — on trzymał tylko część konta i tylko przez część tego "
        "czasu). {note}",

    # ---------- research screens ----------
    "research.intro": "Narzędzia badawcze — **nie prowadzą portfela**. Odpowiadają na pytanie "
        "„czy ten pomysł się broni?”, a nie „ile masz teraz”.",
    "research.tab.crosssec": "📊 Ranking przekrojowy",
    "research.tab.screen": "🧭 Przesiew dywersyfikacji",
    "research.unknown_date": "nieznana data",
    "research.timeout": "Przekroczono limit czasu (10 min).",
    "research.no_results": "Brak zapisanych wyników dla: {name}.",
    "research.run_to_see": "Uruchom badanie, żeby zobaczyć tu wyniki:",
    "research.last_run": "Ostatnie przeliczenie: **{when}**",
    "research.recompute": "Przelicz na zapisanych danych",
    "research.done": "Gotowe.",
    "research.failed": "Nie udało się.",
    "research.spinner.matrix": "Liczę macierz...",
    "research.spinner.correlations": "Liczę korelacje...",
    "research.sigmas": "{n} odchyleń od zera",
    "research.sigmas.help": "Poniżej 2 odchyleń wynik jest nieodróżnialny od przypadku — bez "
        "względu na to, jak duży jest procent.",
    "research.sign.consistent": "spójny znak",
    "research.sign.consistently_negative": "spójnie ujemny",
    "research.sign.flips": "znak się zmienia → to szum",
    "research.window_line": "{icon} **{market} · {direction}** — bije poprzeczkę w "
        "{wins}/{total} oknach, {tail}",
    "research.crosssec.title": "Ranking przekrojowy",
    "research.crosssec.name": "ranking przekrojowy",
    "research.crosssec.help": "Kupuj najsilniejsze aktywa, sprzedawaj najsłabsze — zakład na "
        "**różnicę między aktywami**, nie na kierunek rynku.",
    "research.crosssec.luck_question": "**Czy wynik jest odróżnialny od szczęścia?**",
    "research.crosssec.all_noise": "Żaden wariant nie osiąga 2 odchyleń od zera. **Te procenty "
        "nie są przewagą** — mieszczą się w tym, co daje przypadek.",
    "research.crosssec.all_windows": "**Wszystkie okna** — czy znak się trzyma?",
    "research.crosssec.hurdle_help": "Poprzeczka zależy od ekspozycji: wariant *tylko long* "
        "mierzy się z koszykiem kup&trzymaj, *long-short* (neutralny rynkowo) z gotówką.",
    "research.crosssec.survivorship": "**Główne zastrzeżenie: błąd przetrwania.** Uniwersum "
        "krypto to pary, które *dotrwały* do dziś — bez LUNA, bez FTT. Do tego wariant "
        "long-short wymaga kontraktów wieczystych, a koszt funding nie jest w ogóle "
        "modelowany. To pomiar hipotezy, nie strategia.",
    "research.screen.title": "Przesiew dywersyfikacji",
    "research.screen.name": "przesiew dywersyfikacji",
    "research.screen.help": "Pytanie o ryzyko, nie o prognozę: jeśli rynek światowy "
        "(**{benchmark}**) spada, co *nie* spada razem z nim?",
    "research.screen.as_of": "⏳ To jest przesiew **na dzień {date}** — pokazuje tylko to, co "
        "było wiadome wtedy, a nie stan na dziś. Przeliczono {when}.",
    "research.screen.negatively_correlated": "Ujemnie skorelowane",
    "research.screen.n_of_m": "{n} z {m}",
    "research.screen.passes": "Przechodzi przesiew",
    "research.screen.passes.help": "Niska korelacja, stabilna w czasie, dodatni zwrot.",
    "research.screen.negative_and_earning": "Ujemne i zarabiające",
    "research.screen.negative_and_earning.help": "Aktywa naprawdę ujemnie skorelowane, które "
        "przy tym nie tracą.",
    "research.screen.none_negative": "Wśród aktywów o **dodatnim zwrocie** nie ma ani jednego "
        "ujemnie skorelowanego z rynkiem światowym. To jest wynik, nie brak wyniku: realny cel "
        "to *niska* korelacja, nie ujemna.",
    "research.screen.rolling_matters": "**Kolumny „min/max 3-let.” są ważniejsze niż średnia** "
        "— pokazują, co robiła korelacja w najgorszym momencie. Aktywo o średniej +0,2, które "
        "w kryzysie skacze do +0,75, nie ochroniło portfela wtedy, gdy było potrzebne.",
    "research.screen.regime_warning": "**Ta tabela opisuje reżim, który się właśnie skończył.** "
        "Przesiew uruchomiony na danych do 2016 wskazał obligacje długoterminowe (TLT) jako "
        "wzorowy dywersyfikator — korelacja −0,27 i nigdy dodatnia. Przez następną dekadę TLT "
        "straciło 5,2% rocznie i skoczyło do +0,75 w kryzysie 2022. Sprawdź sam: `--as-of` "
        "sprzed dziesięciu lat.",
    "research.screen.as_of_input": "Przelicz na dzień (RRRR-MM-DD)",
    "research.screen.as_of_placeholder": "np. 2016-07-30",

    # ---------- verdicts (stored tokens stay Polish; these are their labels) ----------
    "verdict.candidate.label": "KANDYDAT",
    "verdict.candidate.help": "niska korelacja, stabilna, dodatni zwrot",
    "verdict.unstable.label": "NIESTABILNY",
    "verdict.unstable.help": "niska średnio, ale w kryzysie idzie razem z rynkiem",
    "verdict.loses.label": "TRACI",
    "verdict.loses.help": "dywersyfikuje, ale zjada portfel (ujemny zwrot)",
    "verdict.trap.label": "PUŁAPKA",
    "verdict.trap.help": "ujemna korelacja z konstrukcji — płaci za nią erozją kapitału",
    "verdict.correlated.label": "SKORELOWANY",
    "verdict.correlated.help": "porusza się razem z rynkiem — nie dywersyfikuje",

    # ---------- research table columns ----------
    "col.market": "rynek",
    "col.direction": "kierunek",
    "col.window": "okno",
    "col.total_return_pct": "wynik %",
    "col.hurdle_pct": "poprzeczka %",
    "col.excess_vs_hurdle_pp": "nadwyżka pkt",
    "col.sharpe": "Sharpe",
    "col.max_drawdown_pct": "obsunięcie %",
    "col.avg_net_exposure_pct": "netto %",
    "col.corr": "korelacja",
    "col.roll_min": "min 3-let.",
    "col.roll_max": "max 3-let.",
    "col.cagr_pct": "CAGR %",
    "col.months": "mies.",
    "col.asset": "aktywo",
    "col.as_of": "na dzień",
    "col.verdict": "werdykt",
    # ---------- engine alerts (journalled, webhooked, replayed in the panel) ----------
    "alert.config": "zmieniono ustawienia: {changes}",
    "alert.kill_switch": "dzienny limit straty osiągnięty — nowe wejścia zablokowane",
    "alert.drawdown": "obsunięcie {dd}% od szczytu kapitału",
    "alert.trade_open": "{symbol} otwarto {side} @ {price} (p={prob})",
    "alert.trade_close": "{symbol} zamknięto {side} ({reason}) PnL {pnl} USDT",
    "alert.trade_rollover": "{symbol} przedłużono {side} @ {price} (p={prob}, zamiast wyjścia "
        "{reason})",
    "alert.connection.lost": "brak połączenia z giełdą — ponawiam, na razie nie handluję",
    "alert.connection.back": "połączenie z giełdą wróciło — bot znowu czyta rynek",
    "alert.initial_allocation": "pierwsza alokacja koszyka",
    "alert.rebalance": "rebalans do wag docelowych (drift {drift} pkt)",
    "alert.portfolio_drawdown": "obsunięcie {dd}% od szczytu wartości portfela",

    # ---------- config store ----------
    "store.forbidden_fields": "Tych pól nie można zmieniać z panelu: {fields}",
    "store.value_rejected": "Wartość odrzucona, nic nie zapisano:",
    # ---------- printed portfolio report ----------
    "report.trend.on": "WŁĄCZONY",
    "report.trend.off": "wyłączony",
    "report.portfolio.title": "TRADEMON — RAPORT PORTFELA (rebalanser)",
    "report.portfolio.period": "Okres: {start} .. {end} ({bars} dni handlowych)",
    "report.portfolio.basket": "Koszyk: {basket}   filtr trendu: {trend}",
    "report.portfolio.strategy": "  Strategia (rebalans):  {ret}%   CAGR {cagr}%/rok   "
        "Sharpe {sharpe}   max DD {dd}%",
    "report.portfolio.benchmark": "  Benchmark (kup i trzymaj): {ret}%   Sharpe {sharpe}   "
        "max DD {dd}%",
    "report.portfolio.excess": "  Przewaga nad benchmarkiem: {excess} pkt proc.",
    "report.portfolio.volatility": "  Zmienność (roczna): {vol}%",
    "report.portfolio.counts": "  Rebalansów: {rebalances}   transakcji: {trades}   "
        "prowizje: {fees}",
    "report.portfolio.verdict.beat": "WNIOSEK: rebalans POBIŁ proste trzymanie koszyka "
        "po kosztach.",
    "report.portfolio.verdict.missed": "WNIOSEK: rebalans NIE pobił prostego trzymania "
        "koszyka po kosztach.",
    "report.portfolio.caveat": "Uwaga: wartość rebalansu to dyscyplina i kontrola ryzyka, "
        "nie „alfa”. Wynik zależy od okresu; to narzędzie edukacyjne, nie porada "
        "inwestycyjna.",

    # ---------- diversification screen (printed) ----------
    "screen.no_candidates": "Brak kandydatów z wystarczającą historią.",
    "screen.negatives": "Aktywów o UJEMNEJ korelacji z {benchmark}: {n} z {total}.",
    "screen.none_negative.1": "  Żadne — i to jest właśnie wynik: wśród sensownych aktywów",
    "screen.none_negative.2": "  ujemna korelacja z rynkiem światowym praktycznie nie "
        "istnieje.",
    "screen.none_negative.3": "  Realny cel to NISKA korelacja przy dodatnim zwrocie.",
    "screen.keeper": "{symbol} (kor. {corr}, CAGR {cagr}%)",
    "screen.keepers": "Przechodzą przesiew ({n}): {names}",
    "screen.no_keepers.1": "Nic nie przechodzi przesiewu — żadne aktywo nie łączy niskiej",
    "screen.no_keepers.2": "korelacji, jej stabilności i dodatniego zwrotu.",
    "screen.unstable_item": "{symbol} (do {roll_max})",
    "screen.unstable": "Nisko skorelowane ŚREDNIO, ale zawodzą w kryzysie: {names}",
    "screen.trap_item": "{symbol} ({cagr}%/rok)",
    "screen.traps": "Ujemny zwrot — balast, który topi łódź: {names}",

    # ---------- cross-sectional verdict (printed) ----------
    "hurdle.basket": "koszyk",
    "hurdle.cash": "gotówkę",
    "verdict.sign.consistent": "SPÓJNY znak",
    "verdict.sign.negative": "SPÓJNIE UJEMNY",
    "verdict.sign.flips": "znak SIĘ ZMIENIA -> to szum",
    "verdict.line": "{market} {direction}: bije {hurdle} w {wins}/{total} oknach, nadwyżka "
        "od {lo} do {hi} pkt (rozrzut {spread} pkt) — {tail}",

    # ---------- HTML backtest report ----------
    "report.html.title": "TraDaemon 👹💰 — raport backtestu",
    "report.html.subtitle": "Okres: {start} .. {end} · timeframe {timeframe} · {pairs} par",
    "report.html.verdict": "WERDYKT: {verdict}",
    "report.html.positive": "DODATNI po kosztach",
    "report.html.negative": "UJEMNY po kosztach",
    "report.html.avg_at_work": "W grze (śr.)",

    # ---------- book backtest table (fixed-width) ----------
    "report.book.period": "okres: {start} .. {end}  timeframe {timeframe}",
    "report.book.pairs": "par",
    "report.book.col.board": "plansza",
    "report.book.col.allocation": "przydział",
    "report.book.col.cap": "limit",
    "report.book.col.result": "wynik",
    "report.book.col.sharpe": "sharpe",
    "report.book.col.max_dd": "maxDD",
    "report.book.col.trades": "trans.",
    "report.book.col.signals": "sygnały",
    "report.book.col.no_slot": "bez slotu",
    "report.book.col.in_market": "w rynku",
    # ---------- research CLI reports (shown in the panel's research tab) ----------
    "cli.crosssec.no_results": "Brak wyników — najpierw pobierz dane (--refresh).",
    "cli.crosssec.whole": "CAŁOŚĆ",
    "cli.crosssec.title": "MODUŁ 3: RANKING PRZEKROJOWY — ten sam kod na dwóch rynkach",
    "cli.crosssec.hurdle_note": "Poprzeczka zależy od ekspozycji: long_only (~100% netto) "
        "mierzy się\nz koszykiem kup&trzymaj, long_short (~0% netto) z gotówką. "
        "Porównywanie\nksiążki neutralnej rynkowo z w pełni długim koszykiem to ten sam "
        "błąd\nniedopasowanej ekspozycji, który zawyżał ocenę Modułu 1.",
    "cli.crosssec.sign_question": "CZY ZNAK SIĘ TRZYMA NA ROZŁĄCZNYCH OKNACH?",
    "cli.crosssec.luck_question": "CZY WYNIK JEST ODRÓŻNIALNY OD SZCZĘŚCIA? (całe okresy)",
    "cli.crosssec.significance_line": "{market} {direction}: wynik {ret}% przy {sigmas} "
        "odchylenia od zera — {tail}",
    "cli.crosssec.significant": "ISTOTNE",
    "cli.crosssec.not_significant": "NIEODRÓŻNIALNE od szumu (potrzeba ~2)",
    "cli.crosssec.whole_is_context": "Okno CAŁOŚĆ jest tylko kontekstem — nakłada się na "
        "okna 1..N,\nwięc nie jest niezależnym potwierdzeniem.",
    "cli.screen.title": "PRZESIEW DYWERSYFIKACJI — co porusza się inaczej niż {benchmark}?",
    "cli.screen.subtitle": "(korelacje miesięcznych stóp zwrotu, {period})",
    "cli.screen.period.as_of": "{years} lat do {as_of} — TYLKO to, co było wiadome wtedy",
    "cli.screen.period.recent": "ostatnie {years} lat",
    "cli.screen.how_to_read": "JAK TO CZYTAĆ",
    "cli.screen.rolling_matters": "Kolumny „min/max 3-let.” są ważniejsze niż średnia "
        "korelacja: pokazują,\nco robiła korelacja w najgorszym momencie. Aktywo o średniej "
        "+0,2, które\nw kryzysie skacze do +0,75, nie ochroniło portfela wtedy, gdy było "
        "potrzebne.",
    "cli.screen.conclusion": "WNIOSEK",
    "cli.screen.regime_warning": "UWAGA: ta tabela opisuje reżim, który się WŁAŚNIE "
        "SKOŃCZYŁ.\nUruchom `--as-of` sprzed 10 lat i zobacz, co metoda wybrałaby wtedy\n"
        "— wskazała obligacje długoterminowe, które potem straciły 5%/rok\ni przestały "
        "dywersyfikować dokładnie w kryzysie 2022.",
    "col.sigmas_from_zero": "odch. od 0",
    "col.avg_gross_exposure_pct": "w grze %",
    "col.n_rebalances": "rebalansów",
    "col.fees_pct_of_capital": "koszty %",
}
