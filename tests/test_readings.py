"""Which one do you mean? The readings are built in code: the input as typed, up to 2 nearest recorded ideas (shared
content words, Porter-stemmed, stop words dropped, ties to the newest, never one sharing none), one broader reading."""
from knos import porter, readings

INDEX = [{"idea": "a vegan ramen meal kit for college students", "made": "2026-10-22T13:26:44Z"},
         {"idea": "a home battery for apartments", "made": "2026-10-25T10:00:00Z"},
         {"idea": "a probiotic kombucha brand", "made": "2026-10-22T14:09:51Z"}]


def test_the_stemmer_gives_the_papers_own_examples():
    pairs = {"caresses": "caress", "ponies": "poni", "agreed": "agre", "motoring": "motor", "hopping": "hop", "filing": "file",
             "happy": "happi", "relational": "relat", "triplicate": "triplic", "adjustment": "adjust", "generalization": "gener"}
    assert {w: porter.stem(w) for w in pairs} == pairs


def test_the_two_ramen_inputs_get_their_own_words_a_broader_reading_and_the_recorded_ramen_idea():
    for asked, broad in (("a vegan ramen food truck", "a ramen food truck"), ("a late night ramen spot", "a night ramen spot")):
        w = readings.which(asked, INDEX)
        kinds = [r["kind"] for r in w["readings"]]
        assert w["readings"][0] == {"text": asked, "kind": "exact"} and not w["skip"]
        assert "recorded" in kinds and broad in [r["text"] for r in w["readings"]]
        rec = next(r for r in w["readings"] if r["kind"] == "recorded")
        assert rec["text"] == INDEX[0]["idea"] and rec["differs"]["yours"]           # the words that differ are shown
        assert "a home battery for apartments" not in [r["text"] for r in w["readings"]]   # 0 shared words: never offered
    w = readings.which("a vegan ramen food truck", INDEX)
    assert next(r for r in w["readings"] if r["kind"] == "recorded")["differs"] == {"theirs": "meal kit college students", "yours": "food truck"}


def test_a_recorded_idea_word_for_word_needs_no_step_and_a_tie_goes_to_the_newest():
    assert readings.which("A Probiotic  Kombucha brand", INDEX)["skip"]
    idx = [{"idea": "a ramen bar", "made": "2026-10-01"}, {"idea": "a ramen cart", "made": "2026-10-20"}]
    assert [r["idea"] for r in readings.nearest("ramen soup", idx)] == ["a ramen cart", "a ramen bar"]


def test_a_doi_is_read_from_openalex_and_crossref_answers_when_openalex_does_not():
    oa = {"title": "Deep learning", "publication_year": 2015, "cited_by_count": 84078, "doi": "https://doi.org/10.1038/nature14539",
          "concepts": [{"display_name": "Deep learning", "score": 0.9}, {"display_name": "Computer science", "score": 0.5}]}
    got = readings.paper("10.1038/nature14539", get=lambda url: oa if "openalex" in url else None)
    assert got["title"] == "Deep learning" and got["year"] == 2015 and got["concepts"][0] == "Deep learning" and got["source"] == "OpenAlex"
    cr = {"message": {"title": ["A Programmable Dual-RNA–Guided DNA Endonuclease in Adaptive Bacterial Immunity"], "issued": {"date-parts": [[2012]]},
                      "is-referenced-by-count": 17000}}
    got = readings.paper("10.1126/science.1225829", get=lambda url: cr if "crossref" in url else None)
    assert got["title"].startswith("A Programmable Dual-RNA") and got["year"] == 2012 and got["source"] == "Crossref"
    w = readings.which("10.1038/nature14539", [], products=[], found={"title": "Deep learning"})
    assert w["kind"] == "paper" and w["name_box"] and w["name_prompt"] == "Name the product this result enables"
