from kebabcase import kebabcase


def test_kebabcase():
    assert kebabcase("Hello, world") == "hello-world"
    assert kebabcase("Knos pays merged work") == "knos-pays-merged-work"
    assert kebabcase("") == ""
