import { architecture } from "./architecture";
import { apiRoutes, apiSurface } from "./api";
import { controlPlane } from "./control-plane";
import { dataPlane } from "./data-plane";
import { federation } from "./federation";
import { observability } from "./observability";
import { snapshot } from "./state";
import { storage } from "./storage";

console.log(architecture.project);
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
console.log(controlPlane.services.join(", "));
console.log(dataPlane.runtimes.join(", "));
console.log(federation.protocol);
console.log(observability.signals.join(", "));
console.log(storage.classes.map((cls) => cls.name).join(", "));
console.log(JSON.stringify(snapshot()));
