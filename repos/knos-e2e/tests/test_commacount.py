from commacount import commacount


def test_commacount():
    assert commacount("a,b,c") == 2
    assert commacount(",") == 1
    assert commacount("none") == 0
    assert commacount("") == 0
