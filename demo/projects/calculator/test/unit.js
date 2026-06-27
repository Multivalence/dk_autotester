const assert = require("node:assert");
const { add, multiply } = require("../src/calculator");

assert.strictEqual(add(2, 3), 5, "2 + 3 should be 5");
assert.strictEqual(multiply(4, 5), 20, "4 * 5 should be 20");

console.log("calculator: unit tests passed");
