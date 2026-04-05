import { architecture } from "./architecture";
import { apiRoutes, apiSurface } from "./api";
import { controlPlane } from "./control-plane";
import { dataPlane } from "./data-plane";
import { federation } from "./federation";
import { observability } from "./observability";
import { server, port } from "./server";
import { snapshot } from "./state";
import { storage } from "./storage";

console.log(`${architecture.project} listening on ${port}`);
console.log(architecture.mission);
console.log("Principles:");
for (const principle of architecture.principles) {
  console.log(`- ${principle}`);
}

console.log("API routes:");
for (const route of apiRoutes) {
  console.log(`- ${route.method} ${route.path} — ${route.description}`);
}

console.log("Surface modules:");
console.log(Object.keys(apiSurface).join(", "));
console.log("State snapshot:", JSON.stringify(snapshot()));
console.log("Modules:", {
  controlPlane: controlPlane.services,
  dataPlane: dataPlane.runtimes,
  federation: federation.protocol,
  observability: observability.signals,
  storage: storage.classes.map((item) => item.name),
});

server;
