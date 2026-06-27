const fs = require("node:fs");
const src = fs.readFileSync(require.resolve("../src/calculator.js"), "utf8");

if (src.includes("var ")) {
  console.error("calculator: lint failed - use let/const instead of var");
  process.exit(1);
}

console.log("calculator: lint passed");
