"""The proof the front doors draw first holds `calls` as a list and `n_calls` as their count. On 26 Oct 2026 the
snapshot held the count in `calls` ({"calls": 18}) and the card's calls panel threw "(r.calls || []).map is not a
function", so the chips did nothing. A proof saved in that shape is read back as a list; the page guards the draw."""
import importlib.util
import re
from pathlib import Path

from knos_wanted import vectors

ROOT = Path(__file__).resolve().parents[3]
BAD = {"hash": "ab" * 32, "idea": "a SYNTHETIC tea", "decision": {"verdict": "OPEN"}, "calls": 18}


def test_the_card_of_a_report_holds_its_calls_as_a_list_and_their_count():
    rep = {"hash": "cd" * 32, "idea": "x", "calls": [{"n": 1, "call": "GET /search", "params": {"query": "x"}, "cached": True,
                                                     "ms": 12, "body_digest": "d", "out": {"answer": "never public"}}]}
    card = vectors._card(rep)
    assert card["calls"] == [{"n": 1, "call": "GET /search", "params": {"query": "x"}, "cached": True, "ms": 12}] and card["n_calls"] == 1


def test_a_proof_saved_with_a_count_is_read_back_as_a_list():
    p = vectors.shape(dict(BAD))
    assert p["calls"] == [] and p["n_calls"] == 18 and isinstance(p["calls"], list)


def test_the_snapshot_script_shapes_what_an_old_app_sends():
    spec = importlib.util.spec_from_file_location("proof_snapshot", ROOT / "scripts" / "proof_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.shape(dict(BAD))
    assert p["calls"] == [] and p["n_calls"] == 18


def test_the_card_reads_calls_only_as_a_list_and_draws_the_past_result_last_inside_try():
    js = (ROOT / "web" / "brand" / "hero.js").read_text(encoding="utf-8")
    assert "(r.calls || []).map" not in js and "Array.isArray(r.calls)" in js
    tail = js[js.index('root.addEventListener("click"'):]
    assert re.search(r"try \{ draw\(r\); \} catch", tail) and "if (carried) shown(carried.proof ? carried : { proof: carried });" in tail
