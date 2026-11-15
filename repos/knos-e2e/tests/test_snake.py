from snake import snake


def test_snake():
    assert snake("Hello, World") == "hello_world"
    assert snake("  Knos 0 3 13 ") == "knos_0_3_13"
    assert snake("") == ""
