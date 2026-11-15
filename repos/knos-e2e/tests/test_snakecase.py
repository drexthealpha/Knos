from snakecase import snakecase


def test_snakecase():
    assert snakecase("Hello, world") == "hello_world"
    assert snakecase("Knos pays merged work") == "knos_pays_merged_work"
    assert snakecase("") == ""
