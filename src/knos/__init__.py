"""knos - Bounties that pay when the pull request is merged with the checks you named passing. Attested by a GitHub-signed workflow run, verified on Solana."""


def version() -> str:
    """The installed version, so nothing is ever told the empty string.

    Read from package metadata rather than repeated here, because a second
    copy of the number is a second thing to forget to bump. It lives in this
    module so `knos --version` and the MCP handshake give the same answer
    without the terminal having to import the MCP SDK to find out. The metadata file beside an installed package is read directly;
    importlib.metadata, which cost more than the rest of `import knos` together, is imported only when that file is
    not there, and never with the package: a workflow's signing job does not ask for the version.
    """
    from pathlib import Path
    home = Path(__file__).resolve().parent
    beside = sorted(home.parent.glob("knos-*.dist-info/METADATA"))     # an install: this package's own metadata is next to it
    if len(beside) == 1:
        try:
            for line in beside[0].read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Version:"):
                    return line.partition(":")[2].strip()
                if not line.strip():        # the headers are over
                    break
        except OSError:
            pass
    from importlib.metadata import PackageNotFoundError, version as _installed      # anything else (an editable install, a source tree): ask Python
    try:
        return _installed("knos")
    except PackageNotFoundError:  # a source tree, not an install
        return "0+unknown"
