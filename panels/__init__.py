"""Self-contained dashboard panels that plug into Market Almanack.

Each module here computes one panel's payload in isolation; the main ``app.py``
only imports the entry point and persists the result via ``store``. Nothing in
this package touches the existing news / screener / analysis panels.
"""
