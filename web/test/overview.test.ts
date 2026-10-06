import { test } from "node:test";
import assert from "node:assert/strict";
import {
  deriveOverview,
  type OverviewInput,
  type ApiResult,
} from "../src/overview.ts";

const ok = <T>(value: T): ApiResult<T> => ({ ok: true, value });
const failed = <T>(): ApiResult<T> => ({ ok: false, error: "offline" });
const healthy: OverviewInput = {
  health: ok({ started: true, degraded: false, memory_jobs: { completed: 2 } }),
  providers: ok([{ name: "deepseek", enabled: true, configured: true }]),
  defaultModel: ok({ provider: "deepseek", model: "deepseek-chat" }),
  channels: ok([]),
  events: ok([]),
  mcp: ok([]),
  skills: ok([]),
  qqConfig: ok(null),
};

test("unconfigured optional integrations do not degrade healthy runtime", () => {
  const result = deriveOverview(healthy);
  assert.equal(result.label, "运行正常");
  assert.equal(result.problems.length, 0);
});

test("failed status APIs produce incomplete state rather than empty healthy state", () => {
  const result = deriveOverview({ ...healthy, mcp: failed() });
  assert.equal(result.label, "检查不完整");
  assert.ok(result.errors.includes("MCP 状态不可用"));
});

test("configured but disconnected QQ requires inspection", () => {
  const result = deriveOverview({
    ...healthy,
    qqConfig: ok({ endpoint: "ws://127.0.0.1:6199/ws" }),
    channels: ok([{ channel: "qq", status: "disconnected" }]),
  });
  assert.equal(result.label, "需要检查");
  assert.ok(result.problems.includes("QQ 未连接"));
});

test("failed event counts are explicitly limited by the caller's recent window", () => {
  const result = deriveOverview({
    ...healthy,
    events: ok([{ status: "failed" }, { status: "processing" }]),
  });
  assert.equal(result.failed, 1);
  assert.equal(result.pending, 1);
  assert.ok(result.problems.includes("1 条失败事件（最近 50 条）"));
});

test("disabled or unavailable default model API is not mistaken for a healthy model", () => {
  const result = deriveOverview({ ...healthy, defaultModel: failed() });
  assert.equal(result.label, "检查不完整");
  assert.ok(result.errors.includes("默认模型状态不可用"));
});
