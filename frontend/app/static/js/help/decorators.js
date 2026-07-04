import { copyText } from "../common/clipboard.js";

export function decorateHeadings(content) {
  const headings = Array.from(content.querySelectorAll("h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]"));
  headings.forEach((heading) => {
    heading.classList.add("help-heading");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-shell btn-shell--compact help-inline-button";
    button.dataset.helpCopyHeadingLink = heading.id;
    button.setAttribute("aria-label", `Copy link to ${heading.textContent?.trim() || "section"}`);
    button.textContent = "Copy link";
    heading.append(" ", button);
  });

  return headings;
}

export function decorateCodeBlocks(content) {
  const blocks = Array.from(content.querySelectorAll("pre > code"));
  blocks.forEach((codeBlock, index) => {
    const pre = codeBlock.parentElement;
    if (!pre || pre.parentElement?.classList.contains("help-code-block")) {
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "help-code-block";
    pre.replaceWith(wrapper);
    wrapper.append(pre);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-shell btn-shell--compact help-code-copy";
    button.dataset.helpCopyCode = String(index);
    button.setAttribute("aria-label", `Copy code block ${index + 1}`);
    button.textContent = "Copy code";
    wrapper.append(button);
  });
}

export function bindCopyActions(refs) {
  refs.content?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const headingButton = target.closest("[data-help-copy-heading-link]");
    if (headingButton instanceof HTMLElement) {
      const headingId = headingButton.dataset.helpCopyHeadingLink;
      const url = new URL(window.location.href);
      url.hash = headingId || "";
      await copyText(url.toString(), "Section link copied.", "Could not copy the section link.");
      return;
    }

    const codeButton = target.closest("[data-help-copy-code]");
    if (codeButton instanceof HTMLElement) {
      const wrapper = codeButton.closest(".help-code-block");
      const code = wrapper?.querySelector("code")?.textContent || "";
      await copyText(code, "Code block copied.", "Could not copy the code block.");
    }
  });
}