export function boolLabel(value) {
  return value ? "Enabled" : "Disabled";
}

export function formatDate(value, fallback = "Unavailable") {
  if (!value) {
    return fallback;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

export function formatDuration(value, fallback = "Unavailable") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }

  return `${Math.round(numeric)} ms`;
}