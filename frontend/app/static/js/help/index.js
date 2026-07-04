import { bindCopyActions, decorateCodeBlocks, decorateHeadings } from "./decorators.js";
import { applySearch, bindSearch, createSearchIndex } from "./search.js";
import { bindScrollSpy } from "./scrollspy.js";

function initializeRefs() {
	return {
		content: document.querySelector("[data-help-content]"),
		searchInput: document.querySelector("[data-help-search]"),
		searchStatus: document.querySelector("[data-help-search-status]"),
		tocLinks: Array.from(document.querySelectorAll("[data-help-toc-link]")),
	};
}

export function initializeHelpPage() {
	if (document.body?.dataset.page !== "help") {
		return;
	}

	const refs = initializeRefs();
	if (!refs.content) {
		return;
	}

	const headings = decorateHeadings(refs.content);
	decorateCodeBlocks(refs.content);
	const blocks = createSearchIndex(refs.content);
	bindCopyActions(refs);
	bindSearch(refs, blocks);
	bindScrollSpy(headings, refs);
	applySearch(refs, blocks);
}

if (typeof document !== "undefined") {
	void initializeHelpPage();
}