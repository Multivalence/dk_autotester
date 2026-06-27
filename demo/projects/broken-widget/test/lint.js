const fs = require("node:fs");
const src = fs.readFileSync(require.resolve("../src/widget.js"), "utf8");

if (src.includes("var ")) {
  console.error("broken-widget: lint failed - use let/const instead of var");
  process.exit(1);
}

console.log("broken-widget: lint passed");
