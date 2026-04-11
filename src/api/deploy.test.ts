import { describe, expect, test } from "bun:test";
import { requestManagedDeploy } from "./deploy-client";

describe("deploy client", () => {
  test("is present as a formal integration client", () => {
    expect(typeof requestManagedDeploy).toBe("function");
  });
});
