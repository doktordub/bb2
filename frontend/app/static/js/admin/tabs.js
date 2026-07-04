export function setActiveTab(runtimeState, refs, tabName, { focusPanel = false } = {}) {
  if (!tabName) {
    return;
  }

  runtimeState.activeTab = tabName;

  refs.tabButtons.forEach((button) => {
    const active = button.dataset.adminTab === tabName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  });

  refs.tabPanels.forEach((panel) => {
    const active = panel.dataset.adminPanel === tabName;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });

  if (focusPanel) {
    const activePanel = refs.tabPanels.find((panel) => panel.dataset.adminPanel === tabName);
    activePanel?.focus();
  }
}

export function bindTabs(runtimeState, refs) {
  if (!refs.tabList || refs.tabButtons.length === 0) {
    return;
  }

  refs.tabList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const button = target.closest("[data-admin-tab]");
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }

    setActiveTab(runtimeState, refs, button.dataset.adminTab);
  });

  refs.tabList.addEventListener("keydown", (event) => {
    const currentIndex = refs.tabButtons.findIndex((button) => button.dataset.adminTab === runtimeState.activeTab);
    if (currentIndex === -1) {
      return;
    }

    const moveToIndex = (index) => {
      const nextButton = refs.tabButtons[index];
      if (!nextButton) {
        return;
      }
      setActiveTab(runtimeState, refs, nextButton.dataset.adminTab);
      nextButton.focus();
    };

    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        moveToIndex((currentIndex + 1) % refs.tabButtons.length);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        moveToIndex((currentIndex - 1 + refs.tabButtons.length) % refs.tabButtons.length);
        break;
      case "Home":
        event.preventDefault();
        moveToIndex(0);
        break;
      case "End":
        event.preventDefault();
        moveToIndex(refs.tabButtons.length - 1);
        break;
      default:
        break;
    }
  });
}

export function hydrateFromQuery(runtimeState, refs) {
  const params = new URLSearchParams(window.location.search);
  const traceId = params.get("trace_id")?.trim();
  const explicitTab = params.get("tab")?.trim();
  if (traceId && refs.traceIdInput) {
    refs.traceIdInput.value = traceId;
  }
  if (traceId) {
    runtimeState.activeTraceId = traceId;
    runtimeState.activeTab = "debug";
  }
  if (explicitTab && refs.tabButtons.some((button) => button.dataset.adminTab === explicitTab)) {
    runtimeState.activeTab = explicitTab;
  }
}