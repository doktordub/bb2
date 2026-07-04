export function bindScrollSpy(headings, refs) {
  if (headings.length === 0 || refs.tocLinks.length === 0 || typeof IntersectionObserver === "undefined") {
    return;
  }

  const linkMap = new Map(refs.tocLinks.map((link) => [link.getAttribute("href"), link]));

  const setActive = (headingId) => {
    linkMap.forEach((link, href) => {
      link.classList.toggle("is-active", href === `#${headingId}`);
    });
  };

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
      if (visible[0]?.target instanceof HTMLElement) {
        setActive(visible[0].target.id);
      }
    },
    {
      rootMargin: "-18% 0px -62% 0px",
      threshold: [0, 1],
    }
  );

  headings.forEach((heading) => observer.observe(heading));
  if (headings[0]) {
    setActive(headings[0].id);
  }
}