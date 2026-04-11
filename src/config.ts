export const cloudConfig = {
  deployUrl: process.env.NEXUS_DEPLOY_URL ?? "",
  deployToken: process.env.NEXUS_DEPLOY_TOKEN ?? "",
};

export function hasDeployIntegration(): boolean {
  return Boolean(cloudConfig.deployUrl.trim() && cloudConfig.deployToken.trim());
}
