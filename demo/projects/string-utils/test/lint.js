const fs = require("node:fs");
const src = fs.readFileSync(require.resolve("../src/string-utils.js"), "utf8");

if (src.includes("var ")) {
  console.error("string-utils: lint failed - use let/const instead of var");
  process.exit(1);
}

console.log("string-utils: lint passed");
