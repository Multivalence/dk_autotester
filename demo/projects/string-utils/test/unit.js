const assert = require("node:assert");
const { capitalize, reverse } = require("../src/string-utils");

assert.strictEqual(capitalize("hello"), "Hello", "capitalize first letter");
assert.strictEqual(reverse("abc"), "cba", "reverse string");

console.log("string-utils: unit tests passed");
