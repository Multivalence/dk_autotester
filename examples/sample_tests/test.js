// Minimal stand-in test suite for the local-folder example.
// Exits 0 on success so `npm test` passes; flip the assertion to see a failure.
const assert = require("node:assert");

assert.strictEqual(1 + 1, 2, "basic arithmetic");
console.log("sample-local: all checks passed");
