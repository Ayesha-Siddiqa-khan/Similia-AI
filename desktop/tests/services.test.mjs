import assert from "node:assert/strict";
import test from "node:test";

import { findFreePort } from "../electron/lib/services.js";

test("findFreePort returns a usable loopback port", async () => {
  const port = await findFreePort();
  assert.equal(typeof port, "number");
  assert.ok(port > 1023 && port < 65536);
});
