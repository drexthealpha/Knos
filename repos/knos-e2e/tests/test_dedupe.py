from dedupe import dedupe


def test_dedupe():
    assert dedupe("a b A c b") == "a b c"
    assert dedupe("") == ""
