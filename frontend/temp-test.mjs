import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ChartRenderer } from "./app/static/js/visualization/chart-renderer.js";
import { ChartInstanceStore } from "./app/static/js/visualization/chart-instance-store.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const artifactPath = path.resolve(__dirname, "../backend/tests/fixtures/visualization/chart_artifact_v1.json");

function createFakeElement(tagName = "div") {
  return {
    tagName: tagName.toUpperCase(),
    className: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    children: [],
    attributes: {},
    append(...children) {
      this.children.push(...children);
    },
    replaceChildren(...children) {
      this.children = [...children];
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
  };
}

globalThis.document = {
  createElement: (tagName) => createFakeElement(tagName),
};

globalThis.window = {
  addEventListener(eventName, callback) {},
  removeEventListener(eventName) {},
};

const createdCharts = [];
globalThis.echarts = {
  graphic: {
    clipRectByRect(shape) {
      return shape;
    },
  },
  init(element) {
    let disposed = false;
    const chart = {
      element,
      options: [],
      setOption(option) {
        this.options.push(option);
      },
      resize() {},
      dispose() {
        disposed = true;
      },
      get disposed() { return disposed; }
    };
    createdCharts.push(chart);
    return chart;
  },
};

async function run() {
  const artifact = JSON.parse(await fs.readFile(artifactPath, "utf-8"));
  
  const instanceStore = new ChartInstanceStore();
  const renderer = new ChartRenderer({ instanceStore });

  const container1 = createFakeElement("figure");
  const container2 = createFakeElement("figure");

  // First render
  renderer.render(container1, artifact, { sessionId: "session-1", messageId: "msg-1" });
  
  // Keep track of the first record
  const record1 = instanceStore.get(artifact.artifact_id);
  const chart1 = createdCharts[0];
  
  console.log("Before second render:");
  console.log("chart1.disposed:", chart1.disposed);
  
  // Second render
  renderer.render(container2, artifact, { sessionId: "session-1", messageId: "msg-2" });
  
  console.log("After second render:");
  console.log("chart1.disposed:", chart1.disposed);
  
  const chartRecords = Array.from(instanceStore.byArtifactId.values());
  console.log("chartRecords length after second render:", chartRecords.length);
  
  const disposeCount = renderer.disposeBySession("session-1");
  console.log("disposeBySession('session-1') returned:", disposeCount);
}

run().catch(console.error);
