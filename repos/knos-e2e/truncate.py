"""Shorten a title for a list."""


def truncate(title: str, width: int) -> str:
    """At most `width` characters, cut at a word boundary, with an ellipsis when anything was cut."""
    if len(title) <= width:
        return title
    cut = title[:width - 1].rsplit(" ", 1)[0] if " " in title[:width - 1] else title[:width - 1]
    return cut.rstrip() + "…"
