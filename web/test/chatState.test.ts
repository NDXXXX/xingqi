import { test } from "node:test";
import assert from "node:assert/strict";
import { isCurrentRequest } from "../src/chatState.ts";

test("late events are accepted only by the request that currently owns the chat", () => {
  const previousRun = {};
  const activeRun = {};
  assert.equal(isCurrentRequest(activeRun, previousRun), false);
  assert.equal(isCurrentRequest(activeRun, activeRun), true);
  assert.equal(isCurrentRequest(null, previousRun), false);
});
