const test = require("node:test");
const assert = require("node:assert");
const { slugify } = require("../../../index.js");

test("punctuation", () => assert.strictEqual(slugify("Hello, World!"), "hello-world"));

test("mixed", () => assert.strictEqual(slugify("  Rock & Roll -- 2  "), "rock-roll-2"));
