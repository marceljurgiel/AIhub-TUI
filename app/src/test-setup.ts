// Preloaded by `bun test` (bunfig.toml): keep test runs out of the user's
// ~/.aihub/opentui-bridge.err.log.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.AIHUB_ERR_LOG = join(mkdtempSync(join(tmpdir(), "aihub-test-")), "bridge.err.log");

// Automatic memory learns after the user goes quiet; tests needn't wait 20 s.
process.env.AIHUB_LEARN_IDLE_MS = "80";
