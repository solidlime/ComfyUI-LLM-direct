import { app } from "../../scripts/app.js";

// Display node id -> DOM element for live reasoning text.
const reasoningWidgets = new Map();

// Do NOT import { api } from "../../scripts/api.js": that shim binds
// window.comfyAPI at module-eval time, which can run before the API bundle is
// ready and yield undefined (widgets still show, but the event listener is
// never registered -> "Unknown message type" in the console). Resolve lazily
// inside setup(), which runs after the frontend is fully initialized.
let reasoningApi = null;

function onReasoning(e) {
  const el = reasoningWidgets.get(String(e.detail.node));
  if (el) {
    el.textContent = e.detail.text;  // 置き換え（追記だと二重表示になる）。innerHTML は XSS 境界なので禁止
  }
}

app.registerExtension({
  name: "llm-direct.reasoning",
  async setup() {
    reasoningApi = window.comfyAPI?.api?.api;
    if (!reasoningApi) {
      console.error("[llm-direct] ComfyAPI not available; reasoning display disabled");
      return;
    }
    reasoningApi.addEventListener("llm_direct_reasoning", onReasoning);
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
      this.addDOMWidget("reasoning", "text", el, { serialize: false, getMinHeight: () => 58 });
      // Node ids from the backend arrive as strings ('279'), while LiteGraph's
      // this.id is a number (279) - normalize both sides to string.
      reasoningWidgets.set(String(this.id), el);
    };
    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      onRemoved?.apply(this, arguments);
      reasoningWidgets.delete(String(this.id));
    };
  },
});
