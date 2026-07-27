"""SQL query builders (SQLAlchemy Core `text()` with bound params).

Read-only against layer-2 (`dim_*`, `fact_*`) and layer-3 (`ml_*`,
`recommendations`) tables. All user-supplied values are passed as bound parameters,
never string-formatted, to avoid injection.
"""
