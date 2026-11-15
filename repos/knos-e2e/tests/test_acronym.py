from acronym import acronym


def test_acronym():
    assert acronym("portable network graphics") == "PNG"
    assert acronym("Knos  pays  work") == "KPW"
    assert acronym("x") == "X"
    assert acronym("") == ""
