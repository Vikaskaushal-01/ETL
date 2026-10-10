"""Wording helpers for messages people read (process logs, review problems, notifications)."""


def plural(count, word: str, many: str = None) -> str:
    """'1 row', '3 rows', '1,200 rows': counts read as sentences instead of 'row(s)'."""
    n = int(count or 0)
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def verb(count, one: str = "is", many: str = "are") -> str:
    return one if int(count or 0) == 1 else many
