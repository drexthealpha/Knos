from camel import camel


def test_camel():
    assert camel("Hello, World") == "helloWorld"
    assert camel("knos pays merged work") == "knosPaysMergedWork"
    assert camel("") == ""
