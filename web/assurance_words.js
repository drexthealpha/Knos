// The assurance of one statement line in the words `knos assurance FILE` prints (src/knos/assurance.py: of_line and
// text). The statement page shows these words, not the receipt's own level: a line of a shadow statement (GitHub's
// answers, which GitHub does not sign) is "not signed" in both places. tests/test_assurance_words.py holds this file
// to the Python's lines for every statement of tests/data/statement and the sample.
import { statementGrn } from "./finance_data.js";

export const FROM_RECEIPT = { reported: "workflow-reported", rerun: "re-executed", agreed: "re-executed", attested: "independently-attested" };
export const REACHABLE = ["workflow-reported", "re-executed"];
export const UNSIGNED_SOURCES = ["shadow"];
export const NOT_EVALUATED = "not evaluated";
export const NOT_SIGNED = "not signed";
export const PROVED_WORDS = "workflow identity proved on chain";

/** assurance.of_line: { level, receipt_level, identity_proved } of one line of statementLines. The recorded
 *  goods-received note's assurance when there is one, else the line's receipt level under the statement's source. */
export function lineAssurance(st, status, ln) {
  let kept = null;
  try { kept = statementGrn(st, status, ln.invoice_line).receipt_of_goods.assured; } catch { kept = null; }
  if (kept && typeof kept === "object" && "level" in kept) return { level: kept.level, receipt_level: kept.receipt_level, identity_proved: Boolean(kept.identity_proved) };
  const was = ln.assurance || (ln.evaluations && ln.evaluations.length ? "reported" : NOT_EVALUATED);
  let level = was !== NOT_EVALUATED && !UNSIGNED_SOURCES.includes(st.source) ? FROM_RECEIPT[was] ?? null : null;
  if (level !== null && !REACHABLE.includes(level)) level = null;          // the Python refuses such a level; the page claims none
  return { level, receipt_level: was, identity_proved: false };
}

/** The line's word, as `knos assurance` prints it after "line N: ". */
export function assuranceWord(a) {
  return a.level || (a.receipt_level !== NOT_EVALUATED ? NOT_SIGNED : NOT_EVALUATED);
}

/** The cell of the statement page: the word, and the chain's check of the workflow identity when it was made. */
export function assuranceHtml(esc, a) {
  return `<span data-assurance="${esc(a.level || "none")}">${esc(assuranceWord(a))}</span>${a.identity_proved ? ` <span class="fine">(${esc(PROVED_WORDS)})</span>` : ""}`;
}
