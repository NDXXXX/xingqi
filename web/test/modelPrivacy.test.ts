import { test } from "node:test";
import assert from "node:assert/strict";
import { isLocalInferenceEndpoint, modelDisclosureKey } from "../src/modelPrivacy.ts";

test("loopback, private network, and local hostnames are treated as local inference", () => {
  for (const endpoint of [
    "http://localhost:8000/v1",
    "http://127.0.0.1:8000/v1",
    "http://192.168.1.10:8000/v1",
    "http://172.20.1.10:8000/v1",
    "http://[::1]:8000/v1",
    "http://inference.local/v1",
  ]) assert.equal(isLocalInferenceEndpoint(endpoint), true, endpoint);
});

test("cloud and unrecognized endpoints are treated as remote", () => {
  for (const endpoint of [undefined, "https://api.example.com/v1", "https://fdcloud.example.com/v1", "not a URL"])
    assert.equal(isLocalInferenceEndpoint(endpoint), false, String(endpoint));
});

test("disclosure acknowledgement is scoped to provider endpoint", () => {
  assert.notEqual(
    modelDisclosureKey({ provider_id: "provider-a", base_url: "https://api.example.com/v1" }),
    modelDisclosureKey({ provider_id: "provider-a", base_url: "https://other.example.com/v1" }),
  );
});
