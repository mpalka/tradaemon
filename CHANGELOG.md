# Historia zmian

Najnowsze na górze. Numer wersji z tego pliku musi zgadzać się z `__version__`
w `src/trademon/__init__.py` — pilnuje tego `tests/test_version.py`.

## 0.1.2 — 2026-08-07

- Dziennik zdarzeń nie wywraca panelu na alercie bez instrumentu (np. zmiana
  konfiguracji). Wiersze dziennika wracają teraz bez pól, których nie miały —
  wcześniej pandas dorabiał je jako NaN, a NaN przechodził przez `if sym:`.

## 0.1.1 — 2026-08-07

- Panel pokazuje numer wersji pod tytułem, na każdym module.
- Wersja trzymana w jednym miejscu (`src/trademon/__init__.py`); `pyproject.toml`
  czyta ją przy budowaniu pakietu.

## 0.1.0

- Pierwsza wersja: silnik krypto-scalpera, zarządca portfela, badania, panel.
