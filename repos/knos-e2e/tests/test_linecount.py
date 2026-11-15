from linecount import linecount


def test_linecount():
    assert linecount("Knos 0.3.25 is out") == 1
    assert linecount("a\nb\n") == 2
    assert linecount("a\nb\nc") == 3
    assert linecount("") == 0
