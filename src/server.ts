import { handleRequest } from "./api/router";

export const port = Number(process.env.PORT ?? "8787");
export const server = Bun.serve({
  port,
  fetch: handleRequest,
});
