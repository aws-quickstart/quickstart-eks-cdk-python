#!/usr/bin/env python3
import os
from aws_cdk import core


from eks_cluster.eks_cluster import EKSClusterStack
import context

app = core.App()

context = context.Context(app)
cdk_context = context.outputs

# Note that if we didn't pass through the ACCOUNT and REGION from these environment context that
# it won't let us create 3 AZs and will only create a max of 2 - even when we ask for 3 in eks_vpc

if cdk_context["account"]:
    account = cdk_context["account"]
else:
    account = os.environ.get("CDK_DEPLOY_ACCOUNT", os.environ["CDK_DEFAULT_ACCOUNT"])

if cdk_context["region"]:
    region = cdk_context["region"]
else:
    region = os.environ.get("CDK_DEPLOY_REGION", os.environ["CDK_DEFAULT_REGION"])

eks_cluster_stack = EKSClusterStack(app, "EKSClusterStack", cdk_context, env=core.Environment(
    account=account,
    region=region))
app.synth()