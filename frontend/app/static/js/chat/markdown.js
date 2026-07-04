function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text = "") {
  return escapeHtml(text)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(?!\*)([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
}

function normalizeFenceLanguage(value = "") {
  return String(value).trim().replace(/[^a-zA-Z0-9_-]/g, "");
}

function pushTextBlock(blocks, type, linesOrItems) {
  if (!Array.isArray(linesOrItems) || linesOrItems.length === 0) {
    return;
  }

  blocks.push({
    type,
    lines: [...linesOrItems],
  });
  linesOrItems.length = 0;
}

function tokenizeMarkdownBlocks(content) {
  const lines = String(content ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  const paragraphLines = [];
  const unorderedItems = [];
  const orderedItems = [];
  const quoteLines = [];
  let codeLines = null;
  let codeLanguage = "";

  function flushTextBlocks() {
    pushTextBlock(blocks, "paragraph", paragraphLines);
    pushTextBlock(blocks, "unordered", unorderedItems);
    pushTextBlock(blocks, "ordered", orderedItems);
    pushTextBlock(blocks, "quote", quoteLines);
  }

  for (const line of lines) {
    if (codeLines) {
      if (/^\s*```/.test(line)) {
        blocks.push({
          type: "code",
          language: codeLanguage,
          content: codeLines.join("\n"),
        });
        codeLines = null;
        codeLanguage = "";
      } else {
        codeLines.push(line);
      }
      continue;
    }

    const fenceMatch = line.match(/^\s*```([^`]*)$/);
    if (fenceMatch) {
      flushTextBlocks();
      codeLines = [];
      codeLanguage = normalizeFenceLanguage(fenceMatch[1]);
      continue;
    }

    if (!line.trim()) {
      flushTextBlocks();
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      pushTextBlock(blocks, "paragraph", paragraphLines);
      pushTextBlock(blocks, "ordered", orderedItems);
      pushTextBlock(blocks, "quote", quoteLines);
      unorderedItems.push(line.replace(/^[-*]\s+/, ""));
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      pushTextBlock(blocks, "paragraph", paragraphLines);
      pushTextBlock(blocks, "unordered", unorderedItems);
      pushTextBlock(blocks, "quote", quoteLines);
      orderedItems.push(line.replace(/^\d+\.\s+/, ""));
      continue;
    }

    if (/^>\s?/.test(line)) {
      pushTextBlock(blocks, "paragraph", paragraphLines);
      pushTextBlock(blocks, "unordered", unorderedItems);
      pushTextBlock(blocks, "ordered", orderedItems);
      quoteLines.push(line.replace(/^>\s?/, ""));
      continue;
    }

    pushTextBlock(blocks, "unordered", unorderedItems);
    pushTextBlock(blocks, "ordered", orderedItems);
    pushTextBlock(blocks, "quote", quoteLines);
    paragraphLines.push(line);
  }

  if (codeLines) {
    blocks.push({
      type: "code",
      language: codeLanguage,
      content: codeLines.join("\n"),
    });
  } else {
    flushTextBlocks();
  }

  return blocks;
}

export function renderMarkdownLite(content) {
  return tokenizeMarkdownBlocks(content)
    .map((block) => {
      if (block.type === "unordered") {
        const items = block.lines.map((line) => `<li>${renderInlineMarkdown(line)}</li>`).join("");
        return `<ul>${items}</ul>`;
      }

      if (block.type === "ordered") {
        const items = block.lines.map((line) => `<li>${renderInlineMarkdown(line)}</li>`).join("");
        return `<ol>${items}</ol>`;
      }

      if (block.type === "quote") {
        return `<blockquote>${block.lines.map((line) => renderInlineMarkdown(line)).join("<br>")}</blockquote>`;
      }

      if (block.type === "code") {
        const languageClass = block.language ? ` class="language-${block.language}"` : "";
        return `<pre><code${languageClass}>${escapeHtml(block.content)}</code></pre>`;
      }

      return `<p>${block.lines.map((line) => renderInlineMarkdown(line)).join("<br>")}</p>`;
    })
    .join("");
}

export { escapeHtml };