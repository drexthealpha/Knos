from dotcase import dotcase


def test_dotcase():
    assert dotcase("Hello, world") == "hello.world"
    assert dotcase("Knos pays merged work") == "knos.pays.merged.work"
    assert dotcase("") == ""
