"""Adapters: the only code that talks to the outside world (warehouse, storage, APIs).

Each adapter exposes a small, typed interface and hides the vendor SDK behind it, so the
services layer can be tested with fakes and the vendor can be swapped without touching
domain logic.
"""
