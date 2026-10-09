// The pages web/app.js shows by itself (its views) and the older hashes that still lead to one. One list, so that the
// router (app.js) and the bar and page morph (front.js) cannot disagree. app.js exports both names; front.js reads them
// here, because app.js imports front.js and a page cannot import the file that imports it before either has run.
export const VIEWS = ["check", "protect", "fund", "claim", "pricing", "records", "network", "build"];
// links from earlier pages and comments; #u=, #r= and #rank= are records
export const ALIAS = { bounty: "fund", money: "fund", numbers: "network", u: "records", r: "records", rank: "records", statement: "records", task: "fund", anyissue: "fund" };

// A PAGE ADDED BY NAME is one line here and nothing else (how, and what each field is: the head of web/mounts.js).
// Keep each entry on ONE line: scripts/build_site.sh reads lines.
export const ADDED = {
  approve: { file: "./approver.js", draw: "renderApprover", nav: "Approve", bar: true },
  rails: { file: "./rails.js", draw: "renderRails", nav: "Pay by bank" },
  enforcement: { file: "./enforce_view.js", draw: "renderEnforcement", nav: "Enforcement", json: "enforce.json" },
  judges: { file: "./judges.js", draw: "renderJudges", nav: "For judges", bar: true, json: "judges.json" },
  finance: { file: "./supplier_finance.js", draw: "renderSupplierFinance", nav: "Supplier finance" },
  payee: { file: "./payee.js", draw: "renderPayee", nav: "Collect payout" },
  vendor: { file: "./vendor.js", draw: "renderVendor", nav: "Vendor pages" },
};
