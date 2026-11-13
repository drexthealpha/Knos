"""The README's old reference sections (Round 9, U1) live in docs/reference/COLOSSEUM.md: what the README's generated
tables used to hold (the table of what is real today, the programs, who can upgrade them, the capabilities) is written
there now. The generators build those tables with links from the repository root; `relink` rewrites them for a page
in docs/reference/."""
import re

PAGE = "docs/reference/COLOSSEUM.md"


def relink(text: str) -> str:
    """Root-relative links made relative to docs/reference/; full URLs, anchors and links already going up are kept."""
    def fix(m: re.Match) -> str:
        url = m.group(2)
        if re.match(r"^(https?:|mailto:|#|/|\.\./)", url):
            return m.group(0)
        if url.startswith("docs/reference/"):
            new = url[len("docs/reference/"):]
        elif url.startswith("docs/"):
            new = "../" + url[len("docs/"):]
        else:
            new = "../../" + url
        return f"{m.group(1)}{new})"
    return re.sub(r"(\]\()([^)\s]+)\)", fix, text)
