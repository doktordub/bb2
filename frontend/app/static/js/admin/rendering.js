import { formatDate as formatDateValue, formatDuration as formatDurationValue } from "../common/formatters.js";

export const formatDate = (value) => formatDateValue(value, "Unavailable");
export const formatDuration = (value) => formatDurationValue(value, "Unavailable");

export function formatJson(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

export function renderList(container, items, buildItem, emptyMessage = "No entries available.") {
  if (!container) {
    return;
  }

  container.innerHTML = "";
  if (!Array.isArray(items) || items.length === 0) {
    const fallback = document.createElement("li");
    fallback.className = "admin-list__item";
    fallback.textContent = emptyMessage;
    container.append(fallback);
    return;
  }

  items.forEach((item, index) => {
    container.append(buildItem(item, index));
  });
}

export function createCatalogItem(title, meta) {
  const listItem = document.createElement("li");
  listItem.className = "admin-list__item";

  const titleElement = document.createElement("span");
  titleElement.className = "admin-list__title";
  titleElement.textContent = title;

  const metaElement = document.createElement("span");
  metaElement.className = "admin-list__meta";
  metaElement.textContent = meta;

  listItem.append(titleElement, metaElement);
  return listItem;
}

export function syncText(elements, text) {
  elements.forEach((element) => {
    if (element) {
      element.textContent = text;
    }
  });
}