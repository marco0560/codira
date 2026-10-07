import assert from "node:assert/strict";
import { format } from "./index.ts";
import { display } from "./consumer.ts";
assert.equal(format("MiXeD"), "MIXED");
assert.equal(format("MiXeD", { mode: "lower" }), "mixed");
assert.equal(display("text"), "TEXT");
console.log("existing behavior passed");
