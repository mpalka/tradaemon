# Disclaimer / Zastrzeżenie

*[English](#english) · [Polski](#polski)*

## English

**TraDaemon is an educational project. It is not investment advice, and it is
not a product.**

It exists to make a few questions about algorithmic trading answerable by
measurement rather than by opinion: does a machine-learning signal survive
transaction costs, does rebalancing a basket beat holding it, does
cross-sectional ranking find anything that is not noise. The answers this
repository has measured are mostly **no**, and they are written down honestly
in [README.md](README.md) and [howitworks.md](howitworks.md) — including the
result that the crypto module's edge is approximately **zero after costs**.

Specifically:

- **Everything ships in paper-trading mode.** Balances, fills and profits shown
  by the dashboard are simulated. No real order is placed and no real money
  moves unless you deliberately change `mode` to `live`, supply exchange API
  keys of your own, and accept the consequences.
- **Backtests are not predictions.** They are fitted to history, they assume a
  cost model that may not match your exchange, and they cannot reproduce
  slippage, outages, or the behaviour of a market that has seen the strategy.
- **A positive paper result is not evidence of an edge.** With a handful of
  trades it is indistinguishable from luck. The research notes in this
  repository repeatedly show measured effects that fail to clear the
  significance bar, and say so.
- **Nothing here is financial, investment, tax, or legal advice.** The author is
  not a licensed advisor. Decisions about your own money are entirely your own.
- **No warranty.** The software is provided "as is" under the
  [MIT License](LICENSE). The authors are not liable for any loss arising from
  its use — financial or otherwise.
- **The dashboard has no authentication.** It binds `0.0.0.0:8501` and lets any
  viewer change the running configuration. Run it on a trusted local network
  only; never port-forward it to the internet.

### What outcome to expect

The realistic expected outcome of running this bot with real money is **a loss**. That is
not modesty about this particular code — it is what the evidence says about retail
algorithmic trading in general, and what this project's own measurements say about
itself.

This project's three modules produced: an edge of approximately **zero after costs**
(crypto scalper), **−33.6 percentage points** against buy & hold over ten years
(portfolio rebalancer), and **1.11 standard deviations** from zero where ~2 is the usual
significance bar (cross-sectional ranking). None of the three cleared the threshold.

The wider literature is consistent, and worth reading first-hand rather than taking this
file's word for it:

- Barber and Odean, *Trading Is Hazardous to Your Wealth* (2000) — the most active
  individual traders underperformed the market substantially after costs.
- Barber, Lee, Liu and Odean on Taiwan (2014) — well under 1% of day traders were
  reliably profitable net of fees.
- Chague, De-Losso and Giovannetti (2020) on Brazilian futures — among those who day
  traded for more than 300 days, the overwhelming majority lost money.
- López de Prado on backtest overfitting — try enough strategy variants on the same
  history and an impressive Sharpe ratio appears by chance. A backtest is not evidence
  unless you account for how many things you tried.

Three structural forces explain it: costs compound against turnover, the counterparties
are better resourced professionals, and backtests systematically overstate what a live
book would have done. This project has been surprised by the third one directly —
conclusions drawn from one year of data reversed on five and a half.

If you trade real money using anything from this repository, you do so on your
own responsibility, with capital you can afford to lose.

## Polski

**TraDaemon to projekt edukacyjny. Nie jest poradą inwestycyjną ani produktem.**

Powstał po to, żeby na kilka pytań o handel algorytmiczny odpowiadał pomiar, a
nie opinia: czy sygnał z uczenia maszynowego przeżywa koszty transakcyjne, czy
rebalansowanie koszyka bije zwykłe trzymanie go, czy ranking przekrojowy
znajduje cokolwiek poza szumem. Odpowiedzi, które to repozytorium zmierzyło, to
w większości **nie** — i są spisane uczciwie w [README.pl.md](README.pl.md)
oraz [howitworks.pl.md](howitworks.pl.md), łącznie z wynikiem, że przewaga
modułu krypto wynosi **około zera po kosztach**.

Konkretnie:

- **Wszystko działa domyślnie na papierze.** Salda, transakcje i zyski pokazane
  w panelu są symulowane. Żadne prawdziwe zlecenie nie idzie na giełdę i żadne
  prawdziwe pieniądze się nie ruszają, dopóki świadomie nie zmienisz `mode` na
  `live`, nie podasz własnych kluczy API i nie przyjmiesz konsekwencji.
- **Backtest to nie prognoza.** Jest dopasowany do historii, zakłada model
  kosztów, który może nie odpowiadać Twojej giełdzie, i nie odtworzy poślizgu,
  awarii ani zachowania rynku, który już tę strategię widział.
- **Dodatni wynik na papierze nie jest dowodem przewagi.** Przy kilkunastu
  transakcjach jest nie do odróżnienia od szczęścia. Notatki badawcze w tym
  repozytorium raz po raz pokazują efekty, które nie przechodzą progu
  istotności — i mówią to wprost.
- **Nic tutaj nie jest poradą finansową, inwestycyjną, podatkową ani prawną.**
  Autor nie jest licencjonowanym doradcą. Decyzje o własnych pieniądzach
  podejmujesz wyłącznie sam.
- **Brak gwarancji.** Oprogramowanie jest udostępnione „tak jak jest" na
  [licencji MIT](LICENSE). Autorzy nie odpowiadają za żadną stratę wynikłą z
  jego użycia — finansową ani inną.
- **Panel nie ma logowania.** Nasłuchuje na `0.0.0.0:8501` i pozwala każdemu
  oglądającemu zmienić konfigurację działającego bota. Uruchamiaj go wyłącznie
  w zaufanej sieci lokalnej; nigdy nie przekierowuj tego portu z internetu.

### Jakiego wyniku się spodziewać

Realistycznie oczekiwanym wynikiem uruchomienia tego bota na prawdziwych pieniądzach jest
**strata**. To nie jest skromność wobec tego konkretnego kodu — to, co mówią dowody
o detalicznym handlu algorytmicznym w ogóle, i to, co pomiary tego projektu mówią o nim
samym.

Trzy moduły tego projektu dały: przewagę około **zera po kosztach** (krypto-scalper),
**−33,6 punktu procentowego** względem kup&trzymaj na dziesięciu latach (rebalanser
portfela) oraz **1,11 odchylenia standardowego** od zera, gdzie zwykłą poprzeczką
istotności jest ~2 (ranking przekrojowy). Żaden z trzech nie przekroczył progu.

Szersza literatura jest zgodna i warto ją przeczytać u źródła, a nie wierzyć temu plikowi:

- Barber i Odean, *Trading Is Hazardous to Your Wealth* (2000) — najbardziej aktywni
  inwestorzy indywidualni wypadali po kosztach wyraźnie gorzej niż rynek.
- Barber, Lee, Liu i Odean na danych z Tajwanu (2014) — grubo poniżej 1% day-traderów
  było trwale rentownych po opłatach.
- Chague, De-Losso i Giovannetti (2020) na brazylijskich kontraktach terminowych — wśród
  handlujących dłużej niż 300 dni przeważająca większość traciła pieniądze.
- López de Prado o przeuczeniu backtestu — przetestuj dość wariantów na tej samej
  historii, a imponujący Sharpe pojawi się przypadkiem. Backtest nie jest dowodem, dopóki
  nie policzysz, ile rzeczy sprawdziłeś.

Tłumaczą to trzy siły strukturalne: koszty kumulują się z obrotem, po drugiej stronie
stoją lepiej wyposażeni profesjonaliści, a backtesty systematycznie zawyżają to, co
zrobiłaby żywa księga. Ten projekt został zaskoczony dokładnie tym trzecim — wnioski
z roku danych odwróciły się na pięciu i pół.

Jeśli handlujesz prawdziwymi pieniędzmi przy użyciu czegokolwiek z tego
repozytorium, robisz to na własną odpowiedzialność i za kapitał, którego stratę
możesz znieść.
