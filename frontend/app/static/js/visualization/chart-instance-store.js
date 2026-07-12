function safeCall(callback) {
  if (typeof callback === "function") {
    callback();
  }
}

export class ChartInstanceStore {
  constructor() {
    this.byArtifactId = new Map();
    this.byElement = new WeakMap();
  }

  get(artifactId) {
    return this.byArtifactId.get(artifactId) || null;
  }

  getByElement(element) {
    return this.byElement.get(element) || null;
  }

  upsert(record) {
    if (!record || typeof record !== "object") {
      throw new TypeError("Chart instance records must be objects.");
    }
    if (!record.artifactId) {
      throw new TypeError("Chart instance records require artifactId.");
    }
    if (!record.element || typeof record.element !== "object") {
      throw new TypeError("Chart instance records require element.");
    }

    const existingByArtifact = this.get(record.artifactId);
    if (existingByArtifact && existingByArtifact !== record) {
      this.dispose(record.artifactId);
    }

    const existingByElement = this.getByElement(record.element);
    if (existingByElement && existingByElement.artifactId !== record.artifactId) {
      this.dispose(existingByElement.artifactId);
    }

    const frozenRecord = {
      ...record,
      dispose: typeof record.dispose === "function" ? record.dispose : () => {},
      resize: typeof record.resize === "function" ? record.resize : () => {},
      update: typeof record.update === "function" ? record.update : () => {},
    };

    this.byArtifactId.set(record.artifactId, frozenRecord);
    this.byElement.set(record.element, frozenRecord);
    return frozenRecord;
  }

  resize(artifactId) {
    const record = this.get(artifactId);
    if (record) {
      record.resize();
    }
    return record;
  }

  dispose(artifactId) {
    const record = this.get(artifactId);
    if (!record) {
      return false;
    }

    this.byArtifactId.delete(artifactId);
    if (record.element && this.byElement.get(record.element)?.artifactId === artifactId) {
      this.byElement.delete(record.element);
    }
    safeCall(record.dispose);
    return true;
  }

  disposeByMessage(messageId) {
    const artifactIds = Array.from(this.byArtifactId.values())
      .filter((record) => record.messageId === messageId)
      .map((record) => record.artifactId);
    artifactIds.forEach((artifactId) => this.dispose(artifactId));
    return artifactIds.length;
  }

  disposeBySession(sessionId) {
    const artifactIds = Array.from(this.byArtifactId.values())
      .filter((record) => record.sessionId === sessionId)
      .map((record) => record.artifactId);
    artifactIds.forEach((artifactId) => this.dispose(artifactId));
    return artifactIds.length;
  }

  disposeAll() {
    const artifactIds = Array.from(this.byArtifactId.keys());
    artifactIds.forEach((artifactId) => this.dispose(artifactId));
    return artifactIds.length;
  }
}