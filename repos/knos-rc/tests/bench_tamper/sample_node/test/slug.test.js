const test = require("node:test");
const assert = require("node:assert");
const { slugify, KNOWN } = require("../index.js");

for (const [s, want] of KNOWN) {
  test(`known: ${s}`, () => assert.strictEqual(slugify(s), want));
}

test("empty", () => assert.strictEqual(slugify(""), ""));
