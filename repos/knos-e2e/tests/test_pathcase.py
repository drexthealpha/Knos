from pathcase import pathcase


def test_pathcase():
    assert pathcase("Hello, world") == "hello.world"
    assert pathcase("Knos pays merged work") == "knos.pays.merged.work"
    assert pathcase("") == ""
