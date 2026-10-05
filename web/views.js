// The pages web/app.js shows by itself (its views) and the older hashes that still lead to one. One list, so that the
// router (app.js) and the bar and page morph (front.js) cannot disagree. app.js exports both names; front.js reads them
// here, because app.js imports front.js and a page cannot import the file that imports it before either has run.
export const VIEWS = ["check", "protect", "fund", "claim", "pricing", "records", "network", "build"];
// links from earlier pages and comments; #u=, #r= and #rank= are records
export const ALIAS = { bounty: "fund", money: "fund", numbers: "network", u: "records", r: "records", rank: "records", statement: "records", task: "fund", anyissue: "fund" };
