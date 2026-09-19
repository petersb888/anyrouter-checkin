const fs = require("fs");
const text = fs.readFileSync("xai_models.html", "utf8");
const re = /\\"id\\":\\"(grok[^\\"]*)\\"/g;
const ids = new Set();
let m;
while ((m = re.exec(text)) !== null) ids.add(m[1]);
console.log("model ids:", [...ids].join("\n"));

// Find price-like fields: look for context around "input" price keys
const priceRe = /\\"(input|output|cache[/]?read|cached_input|per_?[a-z]*)\\":\{[^}]*?\\"[a-z_]+\\":([0-9.]+)/g;
// Simpler: capture chunks around each grok id occurrence showing numeric price fields
for (const id of ids) {
  const idx = text.indexOf('\\"id\\":\\"' + id + '\\"');
  if (idx === -1) continue;
  const chunk = text.slice(idx, idx + 3000);
  const prices = chunk.match(/\\"(input|output|cacheRead|per1M|price[^\\"]*)\\":[^,]{0,80}/g) || [];
  console.log("=== " + id + " ===");
  console.log(prices.slice(0, 30).join("\n"));
}
