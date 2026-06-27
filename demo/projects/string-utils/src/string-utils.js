function capitalize(s) {
  if (!s) return s;
  return s[0].toUpperCase() + s.slice(1);
}

function reverse(s) {
  return s.split("").reverse().join("");
}

module.exports = { capitalize, reverse };
