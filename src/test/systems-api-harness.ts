import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { SystemsApiRegistryData } from "../systems-api/store";

export const emptySystemsApiRegistry: SystemsApiRegistryData = {
  tools: [],
  publicUrls: [],
  history: [],
  exposures: [],
  domains: [],
};

export type SystemsApiTestHarness = {
  handleRequest: (request: Request) => Promise<Response>;
  systemsApiService: typeof import("../systems-api").systemsApiService;
  cleanup: () => void;
};

export async function createSystemsApiTestHarness(registry: SystemsApiRegistryData = emptySystemsApiRegistry): Promise<SystemsApiTestHarness> {
  const originalCwd = process.cwd();
  const tempDir = await mkdtemp(join(tmpdir(), "nexus-cloud-tests-"));
  mkdirSync(join(tempDir, "data"), { recursive: true });
  writeFileSync(join(tempDir, "data", "systems-api-registry.json"), `${JSON.stringify(registry, null, 2)}\n`);
  process.chdir(tempDir);

  try {
    const routerModule = await import("../api/router");
    const systemsApiModule = await import("../systems-api");

    return {
      handleRequest: routerModule.handleRequest,
      systemsApiService: systemsApiModule.systemsApiService,
      cleanup: () => {
        process.chdir(originalCwd);
        rmSync(tempDir, { recursive: true, force: true });
      },
    };
  } catch (error) {
    process.chdir(originalCwd);
    rmSync(tempDir, { recursive: true, force: true });
    throw error;
  }
}
