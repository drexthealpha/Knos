// Numbers and sums of money in the reader's own locale, and numbers typed in any of the digit sets people use
// (LAWS/UX/U7.md R13 and R14). The browser's Intl.NumberFormat writes them, so Arabic in Saudi Arabia gets Arabic-Indic
// digits (١٬٢٣٤٫٥), Arabic in the Emirates Latin digits (1,234.5), Persian its own digits (۱٬۲۳۴٫۵), Hindi groups by
// lakh (12,34,567.891), German writes 1.234.567,891, and a currency keeps its own decimals (JPY none, KWD three).
// parse() reads a number typed in Latin, Arabic-Indic, Persian, Devanagari, Bengali or full-width digits, with the
// locale's decimal mark or the Arabic one. The front door loads it (web/door.html, KF.number for its own numbers).
window.KF = window.KF || (() => {
  const loc = (l) => l || document.documentElement.lang || "en";
  function number(n, l, o) { try { return new Intl.NumberFormat(loc(l), o).format(n); } catch (e) { return String(n); } }
  function money(x, currency, l) { try { return new Intl.NumberFormat(loc(l), { style: "currency", currency }).format(x); } catch (e) { return currency + " " + String(x); } }
  const DIGITS = [0x660, 0x6f0, 0x966, 0x9e6, 0xff10];   // the zero of each digit set above, Latin aside
  function marks(l) {
    try { const p = new Intl.NumberFormat(loc(l)).formatToParts(12345.6); return { group: (p.find((x) => x.type === "group") || {}).value || ",", dec: (p.find((x) => x.type === "decimal") || {}).value || "." }; } catch (e) { return { group: ",", dec: "." }; }
  }
  function parse(s, l) {
    let x = "";
    for (const ch of String(s).trim()) { const c = ch.codePointAt(0), z = DIGITS.find((d) => c >= d && c <= d + 9); x += z === undefined ? ch : String(c - z); }
    const m = marks(l);
    x = x.split(m.group).join("").replace(/[\s  ٬]/g, "").replace(/٫/g, ".");
    if (m.dec !== ".") x = x.split(m.dec).join(".");
    const n = Number(x);
    return x !== "" && Number.isFinite(n) ? n : NaN;
  }
  return { number, money, parse };
})();
