import assert from "node:assert/strict";
import test from "node:test";

import { renderMarkdownLite } from "../../app/static/js/chat/markdown.js";

test("renderMarkdownLite keeps fenced code blocks distinct from surrounding markdown", () => {
  const markdown = [
    "Here is a Python example:",
    "```python",
    "print(\"hello\")",
    "if ready:",
    "    print(\"*still code*\")",
    "```",
    "And `inline` markdown after it.",
  ].join("\n");

  const html = renderMarkdownLite(markdown);

  assert.match(html, /<p>Here is a Python example:<\/p>/);
  assert.match(html, /<pre><code class="language-python">print\(&quot;hello&quot;\)\nif ready:\n    print\(&quot;\*still code\*&quot;\)<\/code><\/pre>/);
  assert.match(html, /<p>And <code>inline<\/code> markdown after it\.<\/p>/);
  assert.ok(!html.includes("<em>still code</em>"));
});

test("renderMarkdownLite preserves fenced blocks even when they are not separated by blank lines", () => {
  const html = renderMarkdownLite("Intro\n```json\n{\n  \"ok\": true\n}\n```\nOutro");

  assert.match(html, /<p>Intro<\/p><pre><code class="language-json">\{\n  &quot;ok&quot;: true\n\}<\/code><\/pre><p>Outro<\/p>/);
});