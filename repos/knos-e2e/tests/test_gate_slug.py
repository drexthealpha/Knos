from gate_slug import gate_slug


def test_lower():
    assert gate_slug("ABC") == "abc"
