from slashcase import slashcase


def test_slashcase():
    assert slashcase("Hello, world") == "hello/world"
    assert slashcase("Knos pays merged work") == "knos/pays/merged/work"
    assert slashcase("") == ""
