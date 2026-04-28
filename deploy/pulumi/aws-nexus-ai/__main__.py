import pulumi
import pulumi_aws as aws

config = pulumi.Config()
project_name = config.get("projectName") or "nexus-ai"
environment = config.get("environment") or "prod"
vpc_cidr = config.get("vpcCidr") or "10.50.0.0/16"
allowed_ingress = config.get_object("allowedIngressCidrs") or ["0.0.0.0/0"]

name_prefix = f"{project_name}-{environment}"

tags = {
    "Project": project_name,
    "Environment": environment,
    "ManagedBy": "pulumi",
}

vpc = aws.ec2.Vpc(
    f"{name_prefix}-vpc",
    cidr_block=vpc_cidr,
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={**tags, "Name": f"{name_prefix}-vpc"},
)

igw = aws.ec2.InternetGateway(
    f"{name_prefix}-igw",
    vpc_id=vpc.id,
    tags={**tags, "Name": f"{name_prefix}-igw"},
)

public_subnet = aws.ec2.Subnet(
    f"{name_prefix}-public-0",
    vpc_id=vpc.id,
    cidr_block="10.50.0.0/24",
    map_public_ip_on_launch=True,
    availability_zone=f"{aws.config.region}a",
    tags={**tags, "Name": f"{name_prefix}-public-0", "Tier": "public"},
)

private_subnet = aws.ec2.Subnet(
    f"{name_prefix}-private-0",
    vpc_id=vpc.id,
    cidr_block="10.50.10.0/24",
    availability_zone=f"{aws.config.region}a",
    tags={**tags, "Name": f"{name_prefix}-private-0", "Tier": "private"},
)

route_table = aws.ec2.RouteTable(
    f"{name_prefix}-public-rt",
    vpc_id=vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", gateway_id=igw.id)],
    tags={**tags, "Name": f"{name_prefix}-public-rt"},
)

aws.ec2.RouteTableAssociation(
    f"{name_prefix}-public-rta",
    subnet_id=public_subnet.id,
    route_table_id=route_table.id,
)

app_sg = aws.ec2.SecurityGroup(
    f"{name_prefix}-app-sg",
    description="Nexus AI application security group",
    vpc_id=vpc.id,
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(protocol="tcp", from_port=80, to_port=80, cidr_blocks=allowed_ingress),
        aws.ec2.SecurityGroupIngressArgs(protocol="tcp", from_port=443, to_port=443, cidr_blocks=allowed_ingress),
    ],
    egress=[aws.ec2.SecurityGroupEgressArgs(protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"])],
    tags={**tags, "Name": f"{name_prefix}-app-sg"},
)

data_sg = aws.ec2.SecurityGroup(
    f"{name_prefix}-data-sg",
    description="Nexus AI data-plane security group",
    vpc_id=vpc.id,
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(protocol="tcp", from_port=5432, to_port=5432, security_groups=[app_sg.id]),
        aws.ec2.SecurityGroupIngressArgs(protocol="tcp", from_port=6379, to_port=6379, security_groups=[app_sg.id]),
    ],
    egress=[aws.ec2.SecurityGroupEgressArgs(protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"])],
    tags={**tags, "Name": f"{name_prefix}-data-sg"},
)

pulumi.export("vpcId", vpc.id)
pulumi.export("publicSubnetId", public_subnet.id)
pulumi.export("privateSubnetId", private_subnet.id)
pulumi.export("appSecurityGroupId", app_sg.id)
pulumi.export("dataSecurityGroupId", data_sg.id)
