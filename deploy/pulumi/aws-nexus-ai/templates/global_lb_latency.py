"""Template: latency-based global load balancing with Route53 records and health checks."""

import pulumi
import pulumi_aws as aws

cfg = pulumi.Config()
zone_id = cfg.require("zoneId")
api_hostname = cfg.get("apiHostname") or "api.nexus.local"
primary_region = cfg.get("primaryRegion") or "us-east-1"
secondary_region = cfg.get("secondaryRegion") or "us-west-2"
primary_endpoint = cfg.require("primaryEndpoint")
secondary_endpoint = cfg.require("secondaryEndpoint")

primary_check = aws.route53.HealthCheck(
    "api-primary-health",
    fqdn=primary_endpoint,
    port=443,
    type="HTTPS",
    resource_path="/health",
    failure_threshold=3,
    request_interval=30,
)

secondary_check = aws.route53.HealthCheck(
    "api-secondary-health",
    fqdn=secondary_endpoint,
    port=443,
    type="HTTPS",
    resource_path="/health",
    failure_threshold=3,
    request_interval=30,
)

aws.route53.Record(
    "api-primary-latency",
    zone_id=zone_id,
    name=api_hostname,
    type="CNAME",
    ttl=30,
    records=[primary_endpoint],
    set_identifier="primary-latency",
    health_check_id=primary_check.id,
    latency_routing_policies=[aws.route53.RecordLatencyRoutingPolicyArgs(region=primary_region)],
)

aws.route53.Record(
    "api-secondary-latency",
    zone_id=zone_id,
    name=api_hostname,
    type="CNAME",
    ttl=30,
    records=[secondary_endpoint],
    set_identifier="secondary-latency",
    health_check_id=secondary_check.id,
    latency_routing_policies=[aws.route53.RecordLatencyRoutingPolicyArgs(region=secondary_region)],
)

pulumi.export("routingMode", pulumi.Output.from_input("latency-based"))
