# CLAUDE.md

## Wersjonowanie

Każda zmiana w kodzie podbija ostatnią cyfrę `__version__` w
`src/trademon/__init__.py` (0.1.1 → 0.1.2) i dopisuje linijkę do `CHANGELOG.md`
pod nagłówkiem nowej wersji. To jedyne miejsce z numerem — `pyproject.toml` czyta
go stamtąd przez `[tool.hatch.version]`, więc nie ma czego synchronizować.

Środkowa cyfra rośnie tylko przy dużych rzeczach (nowy moduł, przebudowa) i wtedy
decyduje o tym użytkownik — sam z siebie nie podbijaj minora.

Panel pokazuje ten numer pod tytułem, więc po wdrożeniu na NAS widać z przeglądarki,
czy kontener jest świeży.
