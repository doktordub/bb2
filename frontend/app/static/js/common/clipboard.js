import { showToast } from "./toast.js";

export async function copyText(
  value,
  successMessage,
  failureMessage,
  { emptyTone = "warning", errorTone = "error" } = {}
) {
  if (!value) {
    if (failureMessage) {
      showToast(failureMessage, { tone: emptyTone });
    }
    return false;
  }

  try {
    await navigator.clipboard.writeText(value);
    if (successMessage) {
      showToast(successMessage, { tone: "info" });
    }
    return true;
  } catch (_error) {
    if (failureMessage) {
      showToast(failureMessage, { tone: errorTone });
    }
    return false;
  }
}