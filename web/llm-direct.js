import { app } from "../../scripts/app.js";

// Do NOT import { api } from "../../scripts/api.js": that shim binds
// window.comfyAPI at module-eval time, which can run before the API bundle is
// ready and yield undefined (widgets still show, but the event listener is
// never registered -> "Unknown message type" in the console). Resolve lazily
// inside setup(), which runs after the frontend is fully initialized.

function onReasoning(e) {
  // Never key widgets by node id: onNodeCreated runs while the node id is
  // still the LiteGraph placeholder (-1); the real id is assigned later on
  // graph.add, so an id-keyed Map is always stale. Resolve the node from the
  // graph at event time instead.
  const node = window.app?.graph?.getNodeById(String(e.detail.node));
  if (!node) return;
  const widget = node.widgets?.find((w) => w.name === "reasoning");
  if (widget?.element) {
    widget.element.textContent = e.detail.text;  // 置き換え（追記だと二重表示）。innerHTML は XSS 境界なので禁止
  }
}

app.registerExtension({
  name: "llm-direct.reasoning",
  async setup() {
    const api = window.comfyAPI?.api?.api;
    if (!api) {
      console.error("[llm-direct] ComfyAPI not available; reasoning display disabled");
      return;
    }
    api.addEventListener("llm_direct_reasoning", onReasoning);
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "DirectGGUFPrompt" && nodeData.name !== "DirectOpenAIPrompt") {
      return;
    }
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      const el = document.createElement("div");
      el.style.cssText = "overflow:auto; min-height:58px; max-height:200px; white-space:pre-wrap; font-family:monospace; font-size:11px; padding:2px;";
      this.addDOMWidget("reasoning", "text", el, { serialize: false, hideOnZoom: false, getMinHeight: () => 58 });
    };
  },
});
