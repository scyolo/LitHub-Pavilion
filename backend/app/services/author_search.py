"""Exact name-token discovery; never use search normalization as author identity."""
import unicodedata
import bisect
import json
import re
from pathlib import Path


_UNICODE = json.loads(Path(__file__).with_name('author_unicode.json').read_text('utf-8'))
_ASCII_SEPARATORS = re.compile(r'[^a-z0-9]+')
_RANGES = {key: (tuple(row[0] for row in _UNICODE[key]), tuple(row[1] for row in _UNICODE[key]))
           for key in ('assigned', 'alphanumeric', 'marks')}


def _in_category(char, category):
    starts, ends = _RANGES[category]
    point = ord(char)
    index = bisect.bisect_right(starts, point) - 1
    return index >= 0 and point <= ends[index]


MAX_AUTHOR_QUERY = 200
MAX_AUTHOR_TOKENS = 12


def normalize_author_name(name: str) -> str:
    """Preserve Unicode letters/numbers while normalizing accents and punctuation."""
    if (name or '').isascii():
        return _ASCII_SEPARATORS.sub(' ', (name or '').lower()).strip()
    # Pin category data to the same contract bundled in the browser. New
    # Unicode assignments cannot become different tokens across runtimes.
    assigned = ''.join(char if _in_category(char, 'assigned') else ' ' for char in name or '')
    decomposed = unicodedata.normalize("NFKD", assigned)
    unmarked = "".join(char for char in decomposed if not _in_category(char, 'marks'))
    lowered = unmarked.lower()
    return " ".join("".join(
        char if _in_category(char, 'alphanumeric') else " "
        for char in lowered
    ).split())


def author_tokens(query: str) -> tuple[str, ...]:
    from fastapi import HTTPException

    from app.api.filtering import bad_request

    if not isinstance(query, str) or len(query) > MAX_AUTHOR_QUERY:
        raise bad_request("作者姓名最多 200 字符")
    tokens = normalize_author_name(query).split()
    if not tokens:
        raise HTTPException(status_code=400, detail={
            "code": "EMPTY_QUERY", "message": "请输入作者姓名"})
    if len(tokens) > MAX_AUTHOR_TOKENS:
        raise bad_request("作者姓名最多 12 个词条")
    return tuple(dict.fromkeys(tokens))


def author_search_terms(name: str) -> str:
    """Encode normalized tokens so FTS cannot change Unicode token boundaries.

    SQLite's unicode61 tokenizer predates modern Unicode. ASCII-hex tokens
    keep Chinese, full-width and compatibility characters in the same contract
    as the exported browser index, with neither Porter stemming nor aliases.
    """
    return " ".join("u" + token.encode("utf-8").hex()
                    for token in dict.fromkeys(normalize_author_name(name).split()))


def author_match_expression(tokens: tuple[str, ...]) -> str:
    return " AND ".join('"u' + token.encode("utf-8").hex() + '"' for token in tokens)


def matching_author_names(names, query: str) -> list[str]:
    tokens = set(author_tokens(query))
    return list(dict.fromkeys(name for name in names
                             if tokens.issubset(normalize_author_name(name).split())))


def rebuild_author_search(connection) -> None:
    """Rebuild only the derived index, using a caller-owned SQL transaction."""
    connection.connection.driver_connection.create_function(
        "api_author_search_terms", 1, author_search_terms, deterministic=True)
    connection.exec_driver_sql("DELETE FROM authors_search_fts")
    connection.exec_driver_sql(
        "INSERT INTO authors_search_fts(rowid, name_tokens) SELECT id, api_author_search_terms(name) FROM authors")
    connection.exec_driver_sql("INSERT INTO authors_search_fts(authors_search_fts) VALUES('integrity-check')")
