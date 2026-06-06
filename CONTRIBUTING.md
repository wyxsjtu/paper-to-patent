# Contributing

Issues and pull requests are welcome.

## Adding terminology

The terminology table in `SKILL.md` maps English SCA/crypto terms to their
standard Chinese equivalents. If you encounter a term that is missing or
incorrectly translated, open a PR that edits the table directly.

## Extending patent search sources

`scripts/patent_search.py` supports three backends (`gov`, `epub`, `google`).
New sources can be added by implementing a function with the signature:

```python
def search_<name>(query: str, max_results: int) -> list[dict]:
    ...
```

Each result dict should contain at least: `source`, `patent_no`, `title`,
`applicant`, `date`, `abstract`, `ipc`, `url`.

## Reporting issues

Please include:
- The paper path (or a minimal reproducible example)
- Output of `python3 scripts/check_env.py`
- The full error message or `[FAIL]` lines from `check_disclosure.py`
