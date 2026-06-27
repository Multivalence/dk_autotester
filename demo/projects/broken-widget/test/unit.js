const assert = require("node:assert");
const { render } = require("../src/widget");

// This assertion fails on purpose to demonstrate FAIL output.
assert.strictEqual(
  render("Save"),
  "<button>Save</button>",
  "render should include the label text",
);

console.log("broken-widget: unit tests passed");
