# The stand-alone verifier

`verify.py` checks a Knos evidence archive with Python 3.8 or later and nothing else. It imports the standard
library only, it does not import `knos`, and it opens no connection.

    python verify.py                  # in a folder an archive was unpacked into
    python verify.py ARCHIVE.zip
    python verify.py FOLDER --strict  # also fail on a note marked INCOMPLETE or UNSIGNED

`knos archive make` puts this same file in every archive, so a holder needs nothing from this repository to
check what they hold. The copy here is byte for byte `src/knos/standalone_verify.py`
(`tests/test_archive.py::test_the_verifier_is_one_file_of_the_standard_library_with_no_knos_and_no_network`).

What it checks, what it only notes and what it cannot know: [docs/RETENTION.md](../../docs/RETENTION.md).
