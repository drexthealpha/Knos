from kebab_upper import kebab_upper


def test_kebab_upper():
    assert kebab_upper(" one two  three ") == "ONE-TWO-THREE"
    assert kebab_upper("") == ""
