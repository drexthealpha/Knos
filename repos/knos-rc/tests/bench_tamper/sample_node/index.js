// The sample project: issue 1 is that slugify keeps punctuation.
const KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]];

function slugify(s) {
  return s.toLowerCase().split(/\s+/).filter(Boolean).join("-");
}

module.exports = { slugify, KNOWN };
