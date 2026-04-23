"""Template: active-active multi-region Nexus AI routing with weighted DNS records."""

import pulumi
import pulumi_aws as aws

cfg = pulumi.Config()
zone_id = cfg.require("zoneId")
api_hostname = cfg.get("apiHostname") or "api.nexus.local"
primary_record = cfg.require("primaryRecord")
secondary_record = cfg.require("secondaryRecord")
primary_weight = cfg.get_int("primaryWeight") or 50
secondary_weight = cfg.get_int("secondaryWeight") or 50

aws.route53.Record(
    "api-primary-weighted",
    zone_id=zone_id,
    name=api_hostname,
    type="CNAME",
    ttl=30,
    records=[primary_record],
    set_identifier="primary",
    weighted_routing_policies=[aws.route53.RecordWeightedRoutingPolicyArgs(weight=primary_weight)],
)

aws.route53.Record(
    "api-secondary-weighted",
    zone_id=zone_id,
    name=api_hostname,
    type="CNAME",
    ttl=30,
    records=[secondary_record],
    set_identifier="secondary",
    weighted_routing_policies=[aws.route53.RecordWeightedRoutingPolicyArgs(weight=secondary_weight)],
)

pulumi.export("routingMode", pulumi.Output.from_input("weighted-active-active"))
