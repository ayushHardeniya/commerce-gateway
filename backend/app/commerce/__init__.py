"""Cart and checkout: deterministic commerce state built on top of the
merchant catalog.

`app.commerce` may depend on `app.catalog` (a cart holds product
references; checkout revalidates against live catalog state). Nothing in
`app.catalog` depends on `app.commerce`. Business rules — availability
checks, price-snapshot revalidation, total calculation — live in each
submodule's `service.py`, never in a router and never in agent/Gemini code.
"""
