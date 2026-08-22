import { app } from "../../scripts/app.js";

// Do NOT import { api } from "../../scripts/api.js": that shim binds
// window.comfyAPI at module-eval time, which can run before the API bundle is
// ready and yield undefined (widgets still show, but the event listener is
// never registered -> "Unknown message type" in the console). Resolve lazily
// inside setup(), which runs after the frontend is fully initialized.

function onReasoning(e) {
  // The WS event carries the emitting LLM node id; update every
  // LLMThinkingPreview node whose input link originates from it.
  const graph = window.app?.graph;
  if (!graph) return;
  for (const node of graph._nodes) {
    if (node.type !== "LLMThinkingPreview") continue;
    const link = node.getInputLink(0);
    if (!link || String(link.origin_id) !== String(e.detail.node)) continue;
    const widget = node.widgets?.find((w) => w.name === "reasoning");
    if (!widget?.element) continue;
    const el = widget.element;
    const stickToBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.textContent = e.detail.text;  // 置き換え（追記だと二重表示）。innerHTML は XSS 境界なので禁止
    if (stickToBottom) el.scrollTop = el.scrollHeight;  // 最下部表示中のみ追従（過去ログを読んでいる最中は邪魔しない）
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
    if (nodeData.name !== "LLMThinkingPreview") {
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
