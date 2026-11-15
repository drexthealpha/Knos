from titlecase import titlecase


def test_titlecase():
    assert titlecase("hello WORLD") == "Hello World"
    assert titlecase("  knos   pays merged work ") == "Knos Pays Merged Work"
    assert titlecase("") == ""
