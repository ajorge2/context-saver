import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { indexPayload, branchClosure, filterLayerNodes } = require("../../plugins/thread-tree/assets/viewer/context-explorer-model.js");

function fixture() {
  return {
    layers: {
      subject: [{ id: "s1" }, { id: "s2" }],
      broad_topic: [{ id: "b1" }, { id: "b2" }],
      specific_topic: [{ id: "t1" }, { id: "t2" }, { id: "t3" }],
      specific_message: [{ id: "m1" }, { id: "m2" }, { id: "m3" }],
    },
    edges: [
      { child_id: "b1", parent_id: "s1" },
      { child_id: "b2", parent_id: "s2" },
      { child_id: "t1", parent_id: "b1" },
      { child_id: "t2", parent_id: "b1" },
      { child_id: "t3", parent_id: "b2" },
      { child_id: "m1", parent_id: "t1" },
      { child_id: "m2", parent_id: "t2" },
      { child_id: "m3", parent_id: "t3" },
    ],
  };
}

test("a selected node exposes only its ancestors and descendants", () => {
  const payload = fixture();
  const index = indexPayload(payload);
  assert.deepEqual([...branchClosure(index, "t1")].sort(), ["b1", "m1", "s1", "t1"]);
  assert.deepEqual(filterLayerNodes(payload, index, { specific_topic: "t1" }, "subject").map((node) => node.id), ["s1"]);
  assert.deepEqual(filterLayerNodes(payload, index, { specific_topic: "t1" }, "specific_message").map((node) => node.id), ["m1"]);
});

test("one selection per layer composes as an intersection", () => {
  const payload = fixture();
  const index = indexPayload(payload);
  const compatible = { subject: "s1", specific_message: "m2" };
  assert.deepEqual(filterLayerNodes(payload, index, compatible, "broad_topic").map((node) => node.id), ["b1"]);
  assert.deepEqual(filterLayerNodes(payload, index, compatible, "specific_topic").map((node) => node.id), ["t2"]);

  const incompatible = { subject: "s2", specific_message: "m2" };
  assert.deepEqual(filterLayerNodes(payload, index, incompatible, "broad_topic"), []);
});

test("a layer dropdown may replace its own selection without dropping other filters", () => {
  const payload = fixture();
  const index = indexPayload(payload);
  const selected = { subject: "s1", specific_topic: "t1" };
  assert.deepEqual(
    filterLayerNodes(payload, index, selected, "specific_topic", true).map((node) => node.id),
    ["t1", "t2"],
  );
  assert.deepEqual(filterLayerNodes(payload, index, selected, "specific_topic").map((node) => node.id), ["t1"]);
});

test("malformed cyclic edges remain bounded", () => {
  const payload = fixture();
  payload.edges.push({ child_id: "s1", parent_id: "m1" });
  const index = indexPayload(payload);
  assert.deepEqual([...branchClosure(index, "m1")].sort(), ["b1", "m1", "s1", "t1"].sort());
});
