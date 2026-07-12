import { BackendApiError, getJsonDetailed } from "../services/api-client.js";
import { validateChartArtifact } from "./artifact-validator.js";

const DEFAULT_TIMEOUT_MS = 10000;
const DEFAULT_CACHE_LIMIT = 24;
const RETRYABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
const DEFAULT_BASE_ORIGIN = "https://frontend.invalid";

function normalizeString(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readHeader(headers, name) {
  if (!headers || typeof headers.get !== "function") {
    return null;
  }
  const value = headers.get(name);
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function parseCacheControl(headerValue) {
  const directives = String(headerValue || "")
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);

  let maxAgeSeconds = null;
  directives.forEach((directive) => {
    if (!directive.startsWith("max-age=")) {
      return;
    }
    const parsed = Number.parseInt(directive.slice("max-age=".length), 10);
    if (Number.isFinite(parsed) && parsed >= 0) {
      maxAgeSeconds = parsed;
    }
  });

  return {
    noStore: directives.includes("no-store"),
    maxAgeSeconds,
  };
}

function cloneArtifact(artifact) {
  if (typeof globalThis.structuredClone === "function") {
    return globalThis.structuredClone(artifact);
  }
  return JSON.parse(JSON.stringify(artifact));
}

function resolveAllowedOrigins(configuredOrigins) {
  if (Array.isArray(configuredOrigins) && configuredOrigins.length) {
    return configuredOrigins
      .map((value) => normalizeString(value))
      .filter(Boolean);
  }

  const rawOrigins = document.body?.dataset?.visualizationReferenceOrigins;
  if (typeof rawOrigins !== "string" || !rawOrigins.trim()) {
    return [];
  }

  return rawOrigins
    .split(",")
    .map((value) => normalizeString(value))
    .filter(Boolean);
}

function resolveBaseOrigin() {
  return normalizeString(globalThis.location?.origin) || DEFAULT_BASE_ORIGIN;
}

function toCacheKey(artifactId, sessionId) {
  return `${sessionId}::${artifactId}`;
}

function normalizeReferencePath(dataRef, { allowedOrigins = [], baseOrigin = DEFAULT_BASE_ORIGIN } = {}) {
  const value = normalizeString(dataRef);
  if (!value) {
    throw new VisualizationDataLoaderError("Visualization data reference is missing.", {
      code: "missing_data_ref",
    });
  }

  if (value.startsWith("/")) {
    return value;
  }

  let parsed = null;
  try {
    parsed = new URL(value, baseOrigin);
  } catch (_error) {
    throw new VisualizationDataLoaderError("Visualization data reference is invalid.", {
      code: "unsafe_data_ref",
    });
  }

  const candidateOrigin = normalizeString(parsed.origin);
  const allowed = new Set([baseOrigin, ...allowedOrigins]);
  if (!candidateOrigin || !allowed.has(candidateOrigin)) {
    throw new VisualizationDataLoaderError("Visualization data reference is not allowed.", {
      code: "unsafe_data_ref",
    });
  }

  return `${parsed.pathname}${parsed.search}`;
}

function isExpiredArtifact(status, code) {
  return status === 410 || code === "artifact_expired";
}

function resolveBackendErrorMessage(status, code, fallbackMessage) {
  if (typeof fallbackMessage === "string" && fallbackMessage.trim()) {
    return fallbackMessage.trim();
  }

  if (isExpiredArtifact(status, code)) {
    return "Visualization data is no longer available. Regenerate the chart to continue.";
  }
  if (status === 401 || status === 403) {
    return "Visualization data is not available in the current session.";
  }
  if (status === 404) {
    return "The requested visualization is not available.";
  }
  if (status === 409) {
    return "The visualization data no longer matches the current chart contract. Regenerate the chart and try again.";
  }
  if (status === 413) {
    return "The visualization data is too large to load in the current view.";
  }
  if (status === 429) {
    return "Visualization loading is temporarily rate-limited. Try again shortly.";
  }
  return "Visualization data could not be loaded.";
}

export class VisualizationDataLoaderError extends Error {
  constructor(message, { code = "reference_load_error", status = null, retryable = false, details = null, cause = null } = {}) {
    super(message);
    this.name = "VisualizationDataLoaderError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.details = details;
    if (cause) {
      this.cause = cause;
    }
  }
}

export class VisualizationDataLoader {
  constructor({
    requestDetailed = getJsonDetailed,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    cacheLimit = DEFAULT_CACHE_LIMIT,
    allowedOrigins = null,
    now = () => Date.now(),
  } = {}) {
    this.requestDetailed = typeof requestDetailed === "function" ? requestDetailed : getJsonDetailed;
    this.timeoutMs = Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : DEFAULT_TIMEOUT_MS;
    this.cacheLimit = Number.isFinite(cacheLimit) && cacheLimit > 0 ? cacheLimit : DEFAULT_CACHE_LIMIT;
    this.allowedOrigins = resolveAllowedOrigins(allowedOrigins);
    this.baseOrigin = resolveBaseOrigin();
    this.now = typeof now === "function" ? now : () => Date.now();
    this.cache = new Map();
  }

  async loadArtifact(artifactCandidate, { sessionId, signal, limits = {} } = {}) {
    const referenceArtifact = validateChartArtifact(artifactCandidate, limits);
    if (referenceArtifact.data_mode !== "reference") {
      return referenceArtifact;
    }

    const resolvedSessionId = normalizeString(sessionId);
    if (!resolvedSessionId) {
      throw new VisualizationDataLoaderError("Visualization data requires an active session.", {
        code: "missing_session",
      });
    }

    const requestPath = normalizeReferencePath(referenceArtifact.data_ref, {
      allowedOrigins: this.allowedOrigins,
      baseOrigin: this.baseOrigin,
    });
    const cacheKey = toCacheKey(referenceArtifact.artifact_id, resolvedSessionId);
    const cachedArtifact = this.#readCache(cacheKey, {
      dataRef: requestPath,
      sessionId: resolvedSessionId,
    });
    if (cachedArtifact) {
      return cloneArtifact(cachedArtifact);
    }

    const { payload, response } = await this.#requestReference(requestPath, {
      sessionId: resolvedSessionId,
      signal,
    });

    if (!payload || typeof payload !== "object") {
      throw new VisualizationDataLoaderError("Visualization data could not be loaded.", {
        code: "invalid_reference_payload",
      });
    }

    if (normalizeString(payload.session_id) !== resolvedSessionId) {
      throw new VisualizationDataLoaderError("Visualization data is not available in the current session.", {
        code: "artifact_session_mismatch",
      });
    }

    const loadedArtifact = validateChartArtifact(payload.data, limits);
    if (loadedArtifact.artifact_id !== referenceArtifact.artifact_id) {
      throw new VisualizationDataLoaderError("Visualization data did not match the requested artifact.", {
        code: "artifact_identity_mismatch",
      });
    }
    if (loadedArtifact.data_mode !== "inline") {
      throw new VisualizationDataLoaderError("Visualization data did not include inline chart rows.", {
        code: "invalid_reference_payload",
      });
    }

    this.#writeCache(cacheKey, loadedArtifact, {
      dataRef: requestPath,
      sessionId: resolvedSessionId,
      headers: response?.headers,
    });

    return cloneArtifact(loadedArtifact);
  }

  clearSession(sessionId) {
    const resolvedSessionId = normalizeString(sessionId);
    if (!resolvedSessionId) {
      return 0;
    }

    const keys = Array.from(this.cache.entries())
      .filter(([, entry]) => entry.sessionId === resolvedSessionId)
      .map(([key]) => key);
    keys.forEach((key) => this.cache.delete(key));
    return keys.length;
  }

  clearAll() {
    const count = this.cache.size;
    this.cache.clear();
    return count;
  }

  async #requestReference(path, { sessionId, signal } = {}) {
    let attempt = 0;
    while (attempt < 2) {
      attempt += 1;
      try {
        return await this.#requestOnce(path, { sessionId, signal });
      } catch (error) {
        const normalized = error instanceof VisualizationDataLoaderError
          ? error
          : this.#normalizeError(error);
        if (normalized.code === "request_aborted" || !normalized.retryable || attempt >= 2) {
          throw normalized;
        }
      }
    }

    throw new VisualizationDataLoaderError("Visualization data could not be loaded.", {
      code: "reference_load_error",
    });
  }

  async #requestOnce(path, { sessionId, signal } = {}) {
    const controller = new AbortController();
    let timedOut = false;
    let removeAbortListener = null;

    if (signal && typeof signal.addEventListener === "function") {
      const forwardAbort = () => controller.abort();
      signal.addEventListener("abort", forwardAbort, { once: true });
      removeAbortListener = () => signal.removeEventListener("abort", forwardAbort);
      if (signal.aborted) {
        controller.abort();
      }
    }

    const timeoutHandle = globalThis.setTimeout
      ? globalThis.setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, this.timeoutMs)
      : null;

    try {
      return await this.requestDetailed(path, {
        sessionId,
        signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) {
        if (signal?.aborted) {
          throw new VisualizationDataLoaderError("Visualization loading was canceled.", {
            code: "request_aborted",
            cause: error,
          });
        }
        if (timedOut) {
          throw new VisualizationDataLoaderError("Visualization data took too long to load. Try again.", {
            code: "request_timeout",
            retryable: true,
            cause: error,
          });
        }
      }

      throw this.#normalizeError(error);
    } finally {
      if (timeoutHandle != null) {
        globalThis.clearTimeout?.(timeoutHandle);
      }
      removeAbortListener?.();
    }
  }

  #normalizeError(error) {
    if (error instanceof VisualizationDataLoaderError) {
      return error;
    }

    if (error instanceof BackendApiError) {
      const payload = error.payload && typeof error.payload === "object" ? error.payload : null;
      const details = payload?.error && typeof payload.error === "object" ? payload.error : null;
      const code = normalizeString(details?.code) || `http_${error.status || "error"}`;
      const status = Number.isInteger(error.status) ? error.status : null;
      return new VisualizationDataLoaderError(
        resolveBackendErrorMessage(status, code, details?.message),
        {
          code,
          status,
          retryable: details?.retryable === true || RETRYABLE_STATUSES.has(status),
          details: payload,
          cause: error,
        }
      );
    }

    return new VisualizationDataLoaderError(error?.message || "Visualization data could not be loaded.", {
      code: "request_failed",
      cause: error,
    });
  }

  #readCache(cacheKey, { dataRef, sessionId } = {}) {
    const entry = this.cache.get(cacheKey);
    if (!entry) {
      return null;
    }

    if (entry.sessionId !== sessionId || entry.dataRef !== dataRef) {
      this.cache.delete(cacheKey);
      return null;
    }

    if (entry.expiresAt !== null && entry.expiresAt <= this.now()) {
      this.cache.delete(cacheKey);
      return null;
    }

    this.cache.delete(cacheKey);
    this.cache.set(cacheKey, entry);
    return entry.artifact;
  }

  #writeCache(cacheKey, artifact, { dataRef, sessionId, headers } = {}) {
    const etag = readHeader(headers, "etag");
    const cacheControl = parseCacheControl(readHeader(headers, "cache-control"));
    if (cacheControl.noStore) {
      this.cache.delete(cacheKey);
      return;
    }

    const expiresAt = Number.isFinite(cacheControl.maxAgeSeconds) && cacheControl.maxAgeSeconds > 0
      ? this.now() + (cacheControl.maxAgeSeconds * 1000)
      : null;
    if (expiresAt === null && !etag) {
      this.cache.delete(cacheKey);
      return;
    }

    this.cache.delete(cacheKey);
    this.cache.set(cacheKey, {
      artifact: cloneArtifact(artifact),
      dataRef,
      sessionId,
      etag,
      expiresAt,
    });

    while (this.cache.size > this.cacheLimit) {
      const oldestKey = this.cache.keys().next().value;
      if (!oldestKey) {
        break;
      }
      this.cache.delete(oldestKey);
    }
  }
}