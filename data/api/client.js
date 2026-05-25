(function (global) {
  "use strict";

  var CLIENT_BASE_URL = (function () {
    if (typeof document !== "undefined") {
      var script = document.currentScript;
      if (script && script.src) return new URL("./", script.src).href;
    }
    if (typeof location !== "undefined") {
      return new URL("data/api/", location.href).href;
    }
    return "https://kkkkof2025.github.io/One/data/api/";
  })();

  function defaultBaseUrl() {
    return CLIENT_BASE_URL;
  }

  function apiUrl(path, options) {
    var baseUrl = options && options.baseUrl ? options.baseUrl : defaultBaseUrl();
    return new URL(path, baseUrl).href;
  }

  function nodeId(node) {
    if (typeof node === "string") return node.trim();
    if (node && typeof node === "object") return String(node.id || "").trim();
    return "root";
  }

  function unwrapNodePayload(payload) {
    if (payload && payload.endpoint === "node" && payload.node) return payload.node;
    return payload;
  }

  async function fetchJson(path, options) {
    var fetchImpl = options && options.fetch ? options.fetch : global.fetch;
    if (typeof fetchImpl !== "function") {
      throw new Error("fetch is not available");
    }
    var response = await fetchImpl(apiUrl(path, options), {
      cache: options && options.cache ? options.cache : "no-cache"
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  async function getIndex(options) {
    return fetchJson("index.json", options);
  }

  async function getRoot(options) {
    return unwrapNodePayload(await fetchJson("by-id/root/node.json", options));
  }

  async function getNode(node, options) {
    var id = nodeId(node);
    if (!id) throw new Error("node id is required");
    return unwrapNodePayload(
      await fetchJson("by-id/" + encodeURIComponent(id) + "/node.json", options)
    );
  }

  async function getChildren(node, options) {
    var id = nodeId(node);
    if (!id) throw new Error("node id is required");
    return fetchJson("by-id/" + encodeURIComponent(id) + "/children.json", options);
  }

  async function getEndNode(options) {
    return fetchJson("getEndNode.json", options);
  }

  async function getScanState(options) {
    return fetchJson("getScanState.json", options);
  }

  var api = {
    apiUrl: apiUrl,
    fetchJson: fetchJson,
    getIndex: getIndex,
    getRoot: getRoot,
    getNode: getNode,
    getChildren: getChildren,
    getEndNode: getEndNode,
    getScanState: getScanState
  };

  global.OneKnowledgeApi = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
