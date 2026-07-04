export function createSearchIndex(content) {
  return Array.from(content.children)
    .filter((node) => node instanceof HTMLElement)
    .map((element) => ({
      element,
      text: element.textContent?.trim().toLowerCase() || "",
    }));
}

export function applySearch(refs, blocks) {
  const query = refs.searchInput?.value.trim().toLowerCase() || "";
  let visibleCount = 0;

  blocks.forEach(({ element, text }) => {
    const matches = !query || text.includes(query);
    element.classList.toggle("help-search-hidden", !matches);
    if (matches) {
      visibleCount += 1;
    }
  });

  refs.tocLinks.forEach((link) => {
    const targetSelector = link.getAttribute("href");
    const target = targetSelector ? refs.content?.querySelector(targetSelector) : null;
    const matches = !query || (target?.textContent?.trim().toLowerCase().includes(query) ?? false);
    link.parentElement?.classList.toggle("help-search-hidden", !matches);
  });

  if (!refs.searchStatus) {
    return;
  }

  refs.searchStatus.textContent = query
    ? `${visibleCount} content blocks match \"${refs.searchInput?.value.trim() || ""}\".`
    : "Search headings, paragraphs, lists, and code snippets in the training guide.";
}

export function bindSearch(refs, blocks) {
  refs.searchInput?.addEventListener("input", () => {
    applySearch(refs, blocks);
  });
}