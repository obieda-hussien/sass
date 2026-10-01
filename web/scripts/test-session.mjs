import { mkdtempSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const output = mkdtempSync(resolve(".session-tests-"));
let result = 1;
try {
  const compile = spawnSync(process.execPath, ["node_modules/typescript/bin/tsc",
    "--outDir", output, "--rootDir", ".", "--target", "ES2022", "--module", "commonjs",
    "--moduleResolution", "node", "--esModuleInterop", "--skipLibCheck", "--strict",
    "lib/api.ts", "lib/server-session.ts", "app/web-auth/session/route.ts", "app/web-api/[...path]/route.ts",
  ], { stdio: "inherit" });
  if (compile.status === 0) {
    result = spawnSync(process.execPath, ["--test", "tests/session.test.cjs"], {
      stdio: "inherit", env: { ...process.env, TEST_BUILD_DIR: output },
    }).status ?? 1;
  }
} finally { rmSync(output, { recursive: true, force: true }); }
process.exitCode = result;
