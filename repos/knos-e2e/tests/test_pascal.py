from pascal import pascal


def test_pascal():
    assert pascal("Hello, world") == "HelloWorld"
    assert pascal("knos pays merged work") == "KnosPaysMergedWork"
    assert pascal("") == ""
