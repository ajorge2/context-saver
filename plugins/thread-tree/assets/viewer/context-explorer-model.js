(function attachContextExplorerModel(root) {
  "use strict";

  function indexPayload(payload) {
    const byId = new Map();
    const parents = new Map();
    const children = new Map();
    Object.values(payload?.layers || {}).flat().forEach((node) => byId.set(node.id, node));
    (payload?.edges || []).forEach((edge) => {
      parents.set(edge.child_id, [...(parents.get(edge.child_id) || []), edge.parent_id]);
      children.set(edge.parent_id, [...(children.get(edge.parent_id) || []), edge.child_id]);
    });
    return { byId, parents, children };
  }

  function branchClosure(index, startId) {
    const result = new Set(startId ? [startId] : []);
    const ancestors = [...(index.parents.get(startId) || [])];
    const descendants = [...(index.children.get(startId) || [])];
    while (ancestors.length) {
      const current = ancestors.shift();
      if (!current || result.has(current)) continue;
      result.add(current);
      (index.parents.get(current) || []).forEach((id) => ancestors.push(id));
    }
    while (descendants.length) {
      const current = descendants.shift();
      if (!current || result.has(current)) continue;
      result.add(current);
      (index.children.get(current) || []).forEach((id) => descendants.push(id));
    }
    return result;
  }

  function filterLayerNodes(payload, index, selections, layerKey, ignoreOwnSelection = false) {
    let nodes = [...(payload?.layers?.[layerKey] || [])];
    Object.entries(selections || {}).forEach(([selectedLayer, nodeId]) => {
      if (!nodeId || (ignoreOwnSelection && selectedLayer === layerKey)) return;
      const branch = branchClosure(index, nodeId);
      nodes = nodes.filter((node) => branch.has(node.id));
    });
    if (!ignoreOwnSelection && selections?.[layerKey]) {
      nodes = nodes.filter((node) => node.id === selections[layerKey]);
    }
    return nodes;
  }

  const api = { indexPayload, branchClosure, filterLayerNodes };
  root.ContextExplorerModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
