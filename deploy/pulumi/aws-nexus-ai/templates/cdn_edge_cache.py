"""Template: CloudFront edge cache in front of Nexus AI API."""

import pulumi
import pulumi_aws as aws

cfg = pulumi.Config()
origin_domain = cfg.require("originDomain")

distribution = aws.cloudfront.Distribution(
    "nexus-api-cdn",
    enabled=True,
    is_ipv6_enabled=True,
    origins=[
        aws.cloudfront.DistributionOriginArgs(
            domain_name=origin_domain,
            origin_id="nexus-api-origin",
            custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                http_port=80,
                https_port=443,
                origin_protocol_policy="https-only",
                origin_ssl_protocols=["TLSv1.2"],
            ),
        )
    ],
    default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
        target_origin_id="nexus-api-origin",
        viewer_protocol_policy="redirect-to-https",
        allowed_methods=["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
        cached_methods=["GET", "HEAD", "OPTIONS"],
        forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
            query_string=True,
            headers=["Authorization", "Origin", "Content-Type"],
            cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                forward="all"
            ),
        ),
        min_ttl=0,
        default_ttl=30,
        max_ttl=300,
    ),
    restrictions=aws.cloudfront.DistributionRestrictionsArgs(
        geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(restriction_type="none")
    ),
    viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
        cloudfront_default_certificate=True
    ),
)

pulumi.export("cdnDomainName", distribution.domain_name)
