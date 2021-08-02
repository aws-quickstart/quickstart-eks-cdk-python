"""
Purpose

Example of how to provision an EKS cluster, create the IAM Roles for Service Accounts (IRSA) mappings,
and then deploy various common cluster add-ons (AWS LB Controller, ExternalDNS, EBS/EFS CSI Drivers,
Cluster Autoscaler, AWS Elasticsearch, Prometheus & Grafana, Calico NetworkPolicy enforcement, 
OPA Gatekeeper w/example policies, etc.)

NOTE: This pulls many parameters/options for what you'd like from the cdk.json context section.
Have a look there for many options you can chance to customise this template for your environments/needs.
"""

from aws_cdk import (
    aws_ec2 as ec2,
    aws_eks as eks,
    aws_iam as iam,
    aws_elasticsearch as es,
    aws_logs as logs,
    aws_certificatemanager as cm,  
    core
)
import os

# Import the custom resource to switch on control plane logging from ekslogs_custom_resource.py
from ekslogs_custom_resource import EKSLogsObjectResource

class EKSClusterStack(core.Stack):

    def __init__(self, scope: core.Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Either create a new IAM role to administrate the cluster or create a new one
        if (self.node.try_get_context("create_new_cluster_admin_role") == "True"):
            cluster_admin_role = iam.Role(self, "ClusterAdminRole",
                assumed_by=iam.CompositePrincipal(
                    iam.AccountRootPrincipal(),
                    iam.ServicePrincipal("ec2.amazonaws.com")
                )
            )
            cluster_admin_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": [
                    "eks:DescribeCluster"
                ],
                "Resource": "*"
            }
            cluster_admin_role.add_to_policy(iam.PolicyStatement.from_json(cluster_admin_policy_statement_json_1))
        else:
            # You'll also need to add a trust relationship to ec2.amazonaws.com to sts:AssumeRole to this as well
            cluster_admin_role = iam.Role.from_role_arn(self, "ClusterAdminRole",
                role_arn=self.node.try_get_context("existing_admin_role_arn")
            )
    
        # Either create a new VPC with the options below OR import an existing one by name
        if (self.node.try_get_context("create_new_vpc") == "True"):
            eks_vpc = ec2.Vpc(
                self, "VPC",
                # We are choosing to spread our VPC across 3 availability zones
                max_azs=3,
                # We are creating a VPC that has a /22, 1024 IPs, for our EKS cluster.
                # I am using that instead of a /16 etc. as I know many companies have constraints here
                # If you can go bigger than this great - but I would try not to go much smaller if you can
                # I use https://www.davidc.net/sites/default/subnets/subnets.html to me work out the CIDRs
                cidr=self.node.try_get_context("vpc_cidr"),
                subnet_configuration=[
                    # 3 x Public Subnets (1 per AZ) with 64 IPs each for our ALBs and NATs
                    ec2.SubnetConfiguration(
                        subnet_type=ec2.SubnetType.PUBLIC,
                        name="Public",
                        cidr_mask=self.node.try_get_context("vpc_cidr_mask_public")
                    ), 
                    # 3 x Private Subnets (1 per AZ) with 256 IPs each for our Nodes and Pods
                    ec2.SubnetConfiguration(
                        subnet_type=ec2.SubnetType.PRIVATE,
                        name="Private",
                        cidr_mask=self.node.try_get_context("vpc_cidr_mask_private")
                    )
                ]
            )   
        else:
            eks_vpc = ec2.Vpc.from_lookup(self, 'VPC', vpc_name=self.node.try_get_context("existing_vpc_name"))

        # Create an EKS Cluster
        eks_cluster = eks.Cluster(
            self, "cluster",
            vpc=eks_vpc,
            masters_role=cluster_admin_role,
            # Make our cluster's control plane accessible only within our private VPC
            # This means that we'll have to ssh to a jumpbox/bastion or set up a VPN to manage it
            endpoint_access=eks.EndpointAccess.PRIVATE,
            version=eks.KubernetesVersion.of(self.node.try_get_context("eks_version")),
            default_capacity=0
        )
        # Output the EKS Cluster Name and Export it
        core.CfnOutput(
            self, "EKSClusterName",
            value=eks_cluster.cluster_name,
            description="The name of the EKS Cluster",
            export_name="EKSClusterName"
        )
        # Output the EKS Cluster OIDC Issuer and Export it
        core.CfnOutput(
            self, "EKSClusterOIDCProviderARN",
            value=eks_cluster.open_id_connect_provider.open_id_connect_provider_arn,
            description="The EKS Cluster's OIDC Provider ARN",
            export_name="EKSClusterOIDCProviderARN"
        )
        # Output the EKS Cluster kubectl Role ARN
        core.CfnOutput(
            self, "EKSClusterKubectlRoleARN",
            value=eks_cluster.kubectl_role.role_arn,
            description="The EKS Cluster's kubectl Role ARN",
            export_name="EKSClusterKubectlRoleARN"
        )
        # Output the EKS Cluster SG ID
        core.CfnOutput(
            self, "EKSSGID",
            value=eks_cluster.kubectl_security_group.security_group_id,
            description="The EKS Cluster's kubectl SG ID",
            export_name="EKSSGID"
        )

        # Add a Managed Node Group
        if bool(node_group_spot_type) == True:
            print("This is going to create autoscaling group with capacityType of instance set to spot instances")
            eks_node_group = eks_cluster.add_nodegroup_capacity(
                "cluster-default-ng-spot",
                desired_size=self.node.try_get_context("eks_node_spot_quantity"),
                max_size=self.node.try_get_context("eks_node_spot_max_quantity"),
                disk_size=self.node.try_get_context("eks_node_spot_disk_size"),
                capacity_type=eks.CapacityType.SPOT,
                # The default in CDK is to force upgrades through even if they violate - it is safer to not do that
                force_update=False,
                instance_types=[ec2.InstanceType(self.node.try_get_context("eks_node_spot_instance_type"))],
                release_version=self.node.try_get_context("eks_node_spot_ami_version"),
                key_name=self.node.try_get_context("eks_ssh_key")
            )
            eks_node_group.role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))                 
        else:
            print("This is going to create autoscaling group with capacityType of instance set to on-demand instances")
            eks_node_group = eks_cluster.add_nodegroup_capacity(
                "cluster-default-ng",
                desired_size=self.node.try_get_context("eks_node_quantity"),
                max_size=self.node.try_get_context("eks_node_max_quantity"),
                disk_size=self.node.try_get_context("eks_node_disk_size"),
                # The default in CDK is to force upgrades through even if they violate - it is safer to not do that
                force_update=False,
                instance_types=[ec2.InstanceType(self.node.try_get_context("eks_node_instance_type"))],
                release_version=self.node.try_get_context("eks_node_ami_version"),
                key_name=self.node.try_get_context("eks_ssh_key")
            )
            eks_node_group.role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))                 
        
        # AWS Load Balancer Controller
        if (self.node.try_get_context("deploy_aws_lb_controller") == "True"):
            alb_service_account = eks_cluster.add_service_account(
                "aws-load-balancer-controller",
                name="aws-load-balancer-controller",
                namespace="kube-system"
            )

            # Create the PolicyStatements to attach to the role
            # Got the required policy from https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.2.0/docs/install/iam_policy.json
            alb_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": [
                    "iam:CreateServiceLinkedRole",
                    "ec2:DescribeAccountAttributes",
                    "ec2:DescribeAddresses",
                    "ec2:DescribeAvailabilityZones",
                    "ec2:DescribeInternetGateways",
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeInstances",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeTags",
                    "ec2:GetCoipPoolUsage",
                    "ec2:DescribeCoipPools",
                    "elasticloadbalancing:DescribeLoadBalancers",
                    "elasticloadbalancing:DescribeLoadBalancerAttributes",
                    "elasticloadbalancing:DescribeListeners",
                    "elasticloadbalancing:DescribeListenerCertificates",
                    "elasticloadbalancing:DescribeSSLPolicies",
                    "elasticloadbalancing:DescribeRules",
                    "elasticloadbalancing:DescribeTargetGroups",
                    "elasticloadbalancing:DescribeTargetGroupAttributes",
                    "elasticloadbalancing:DescribeTargetHealth",
                    "elasticloadbalancing:DescribeTags"
                ],
                "Resource": "*"
            }
            alb_policy_statement_json_2 = {
                "Effect": "Allow",
                "Action": [
                    "cognito-idp:DescribeUserPoolClient",
                    "acm:ListCertificates",
                    "acm:DescribeCertificate",
                    "iam:ListServerCertificates",
                    "iam:GetServerCertificate",
                    "waf-regional:GetWebACL",
                    "waf-regional:GetWebACLForResource",
                    "waf-regional:AssociateWebACL",
                    "waf-regional:DisassociateWebACL",
                    "wafv2:GetWebACL",
                    "wafv2:GetWebACLForResource",
                    "wafv2:AssociateWebACL",
                    "wafv2:DisassociateWebACL",
                    "shield:GetSubscriptionState",
                    "shield:DescribeProtection",
                    "shield:CreateProtection",
                    "shield:DeleteProtection"
                ],
                "Resource": "*"
            }
            alb_policy_statement_json_3 = {
                "Effect": "Allow",
                "Action": [
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:RevokeSecurityGroupIngress"
                ],
                "Resource": "*"
            }
            alb_policy_statement_json_4 = {
                "Effect": "Allow",
                "Action": [
                    "ec2:CreateSecurityGroup"
                ],
                "Resource": "*"
            }
            alb_policy_statement_json_5 = {
                "Effect": "Allow",
                "Action": [
                    "ec2:CreateTags"
                ],
                "Resource": "arn:aws:ec2:*:*:security-group/*",
                "Condition": {
                    "StringEquals": {
                        "ec2:CreateAction": "CreateSecurityGroup"
                    },
                    "Null": {
                        "aws:RequestTag/elbv2.k8s.aws/cluster": "false"
                    }
                }
            }
            alb_policy_statement_json_6 = {
                "Effect": "Allow",
                "Action": [
                    "ec2:CreateTags",
                    "ec2:DeleteTags"
                ],
                "Resource": "arn:aws:ec2:*:*:security-group/*",
                "Condition": {
                    "Null": {
                        "aws:RequestTag/elbv2.k8s.aws/cluster": "true",
                        "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                    }
                }
            }
            alb_policy_statement_json_7 = {
                "Effect": "Allow",
                "Action": [
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:RevokeSecurityGroupIngress",
                    "ec2:DeleteSecurityGroup"
                ],
                "Resource": "*",
                "Condition": {
                    "Null": {
                        "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                    }
                }
            }
            alb_policy_statement_json_8 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:CreateLoadBalancer",
                    "elasticloadbalancing:CreateTargetGroup"
                ],
                "Resource": "*",
                "Condition": {
                    "Null": {
                        "aws:RequestTag/elbv2.k8s.aws/cluster": "false"
                    }
                }
            }
            alb_policy_statement_json_9 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:CreateListener",
                    "elasticloadbalancing:DeleteListener",
                    "elasticloadbalancing:CreateRule",
                    "elasticloadbalancing:DeleteRule"
                ],
                "Resource": "*"
            }
            alb_policy_statement_json_10 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:AddTags",
                    "elasticloadbalancing:RemoveTags"
                ],
                "Resource": [
                    "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*",
                    "arn:aws:elasticloadbalancing:*:*:loadbalancer/net/*/*",
                    "arn:aws:elasticloadbalancing:*:*:loadbalancer/app/*/*"
                ],
                "Condition": {
                    "Null": {
                        "aws:RequestTag/elbv2.k8s.aws/cluster": "true",
                        "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                    }
                }
            }
            alb_policy_statement_json_11 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:AddTags",
                    "elasticloadbalancing:RemoveTags"
                ],
                "Resource": [
                    "arn:aws:elasticloadbalancing:*:*:listener/net/*/*/*",
                    "arn:aws:elasticloadbalancing:*:*:listener/app/*/*/*",
                    "arn:aws:elasticloadbalancing:*:*:listener-rule/net/*/*/*",
                    "arn:aws:elasticloadbalancing:*:*:listener-rule/app/*/*/*"
                ]                
            }
            alb_policy_statement_json_12 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:ModifyLoadBalancerAttributes",
                    "elasticloadbalancing:SetIpAddressType",
                    "elasticloadbalancing:SetSecurityGroups",
                    "elasticloadbalancing:SetSubnets",
                    "elasticloadbalancing:DeleteLoadBalancer",
                    "elasticloadbalancing:ModifyTargetGroup",
                    "elasticloadbalancing:ModifyTargetGroupAttributes",
                    "elasticloadbalancing:DeleteTargetGroup"
                ],
                "Resource": "*",
                "Condition": {
                    "Null": {
                        "aws:ResourceTag/elbv2.k8s.aws/cluster": "false"
                    }
                }
            }
            alb_policy_statement_json_13 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:RegisterTargets",
                    "elasticloadbalancing:DeregisterTargets"
                ],
                "Resource": "arn:aws:elasticloadbalancing:*:*:targetgroup/*/*"                
            }
            alb_policy_statement_json_14 = {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:SetWebAcl",
                    "elasticloadbalancing:ModifyListener",
                    "elasticloadbalancing:AddListenerCertificates",
                    "elasticloadbalancing:RemoveListenerCertificates",
                    "elasticloadbalancing:ModifyRule"
                ],
                "Resource": "*"
            }
            
            # Attach the necessary permissions
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_1))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_2))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_3))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_4))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_5))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_6))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_7))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_8))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_9))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_10))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_11))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_12))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_13))
            alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policy_statement_json_14))

            # Deploy the AWS Load Balancer Controller from the AWS Helm Chart
            # For more info check out https://github.com/aws/eks-charts/tree/master/stable/aws-load-balancer-controller
            awslbcontroller_chart = eks_cluster.add_helm_chart(
                "aws-load-balancer-controller",
                chart="aws-load-balancer-controller",
                version="1.2.3",
                release="awslbcontroller",
                repository="https://aws.github.io/eks-charts",
                namespace="kube-system",
                values={
                    "clusterName": eks_cluster.cluster_name,
                    "region": self.region,
                    "vpcId": eks_vpc.vpc_id,
                    "serviceAccount": {
                        "create": False,
                        "name": "aws-load-balancer-controller"
                    },
                    "replicaCount": 2
                }
            )
            awslbcontroller_chart.node.add_dependency(alb_service_account)

        # External DNS Controller
        if (self.node.try_get_context("deploy_external_dns") == "True"):
            externaldns_service_account = eks_cluster.add_service_account(
                "external-dns",
                name="external-dns",
                namespace="kube-system"
            )

            # Create the PolicyStatements to attach to the role
            # NOTE that this will give External DNS access to all Route53 zones
            # For production you'll likely want to replace 'Resource *' with specific resources
            externaldns_policy_statement_json_1 = {
            "Effect": "Allow",
                "Action": [
                    "route53:ChangeResourceRecordSets"
                ],
                "Resource": [
                    "arn:aws:route53:::hostedzone/*"
                ]
            }
            externaldns_policy_statement_json_2 = {
                "Effect": "Allow",
                "Action": [
                    "route53:ListHostedZones",
                    "route53:ListResourceRecordSets"
                ],
                "Resource": [
                    "*"
                ]
            }

            # Attach the necessary permissions
            externaldns_service_account.add_to_policy(iam.PolicyStatement.from_json(externaldns_policy_statement_json_1))
            externaldns_service_account.add_to_policy(iam.PolicyStatement.from_json(externaldns_policy_statement_json_2))

            # Deploy External DNS from the bitnami Helm chart
            # For more info see https://github.com/bitnami/charts/tree/master/bitnami/external-dns
            externaldns_chart = eks_cluster.add_helm_chart(
                "external-dns",
                chart="external-dns",
                version="5.1.3",
                release="externaldns",
                repository="https://charts.bitnami.com/bitnami",
                namespace="kube-system",
                values={
                    "provider": "aws",
                    "aws": {
                        "region": self.region
                    },
                    "serviceAccount": {
                        "create": False,
                        "name": "external-dns"
                    },
                    "podSecurityContext": {
                        "fsGroup": 65534
                    },
                    "replicas": 2
                }
            )
            externaldns_chart.node.add_dependency(externaldns_service_account)    

        # AWS EBS CSI Driver
        if (self.node.try_get_context("deploy_aws_ebs_csi") == "True"):
            awsebscsidriver_service_account = eks_cluster.add_service_account(
                "awsebscsidriver",
                name="awsebscsidriver",
                namespace="kube-system"
            )

            # Create the PolicyStatements to attach to the role
            awsebscsidriver_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": [
                    "ec2:AttachVolume",
                    "ec2:CreateSnapshot",
                    "ec2:CreateTags",
                    "ec2:CreateVolume",
                    "ec2:DeleteSnapshot",
                    "ec2:DeleteTags",
                    "ec2:DeleteVolume",
                    "ec2:DescribeAvailabilityZones",
                    "ec2:DescribeInstances",
                    "ec2:DescribeSnapshots",
                    "ec2:DescribeTags",
                    "ec2:DescribeVolumes",
                    "ec2:DescribeVolumesModifications",
                    "ec2:DetachVolume",
                    "ec2:ModifyVolume"
                ],
                "Resource": "*"
            }

            # Attach the necessary permissions
            awsebscsidriver_service_account.add_to_policy(iam.PolicyStatement.from_json(awsebscsidriver_policy_statement_json_1))

            # Install the AWS EBS CSI Driver
            # For more info see https://github.com/kubernetes-sigs/aws-ebs-csi-driver
            awsebscsi_chart = eks_cluster.add_helm_chart(
                "aws-ebs-csi-driver",
                chart="aws-ebs-csi-driver",
                version="1.2.3",
                release="awsebscsidriver",
                repository="https://kubernetes-sigs.github.io/aws-ebs-csi-driver",
                namespace="kube-system",
                values={
                    "region": self.region,
                    "serviceAccount": {
                        "controller": {
                            "create": False,
                            "name": "awsebscsidriver"
                        }
                    }
                }
            )
            awsebscsi_chart.node.add_dependency(awsebscsidriver_service_account)

        # AWS EFS CSI Driver
        if (self.node.try_get_context("deploy_aws_efs_csi") == "True"):
            awsefscsidriver_service_account = eks_cluster.add_service_account(
                "awsefscsidriver",
                name="awsefscsidriver",
                namespace="kube-system"
            )

            # Create the PolicyStatements to attach to the role
            awsefscsidriver_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": [
                    "elasticfilesystem:DescribeAccessPoints",
                    "elasticfilesystem:DescribeFileSystems"
                ],
                "Resource": "*"
            }
            awsefscsidriver_policy_statement_json_2 = {
                "Effect": "Allow",
                "Action": [
                    "elasticfilesystem:CreateAccessPoint"
                ],
                "Resource": "*",
                "Condition": {
                    "StringLike": {
                    "aws:RequestTag/efs.csi.aws.com/cluster": "true"
                    }
                }
            }
            awsefscsidriver_policy_statement_json_3 = {
                "Effect": "Allow",
                "Action": "elasticfilesystem:DeleteAccessPoint",
                "Resource": "*",
                "Condition": {
                    "StringEquals": {
                    "aws:ResourceTag/efs.csi.aws.com/cluster": "true"
                    }
                }
            }

            # Attach the necessary permissions
            awsefscsidriver_service_account.add_to_policy(iam.PolicyStatement.from_json(awsefscsidriver_policy_statement_json_1))
            awsefscsidriver_service_account.add_to_policy(iam.PolicyStatement.from_json(awsefscsidriver_policy_statement_json_2))
            awsefscsidriver_service_account.add_to_policy(iam.PolicyStatement.from_json(awsefscsidriver_policy_statement_json_3))

            # Install the AWS EFS CSI Driver
            # For more info see https://github.com/kubernetes-sigs/aws-efs-csi-driver
            awsefscsi_chart = eks_cluster.add_helm_chart(
                "aws-efs-csi-driver",
                chart="aws-efs-csi-driver",
                version="2.1.4",
                release="awsefscsidriver",
                repository="https://kubernetes-sigs.github.io/aws-efs-csi-driver/",
                namespace="kube-system",
                values={
                    "controller": {
                        "serviceAccount": {
                            "create": False,
                            "name": "awsefscsidriver"
                        }
                    },
                    "node": {
                        "serviceAccount": {
                            "create": False,
                            "name": "awsefscsidriver"
                        }    
                    }
                }
            )
            awsefscsi_chart.node.add_dependency(awsefscsidriver_service_account)

        # cluster-autoscaler
        if (self.node.try_get_context("deploy_cluster_autoscaler") == "True"):
            clusterautoscaler_service_account = eks_cluster.add_service_account(
                "clusterautoscaler",
                name="clusterautoscaler",
                namespace="kube-system"
            )

            # Create the PolicyStatements to attach to the role
            clusterautoscaler_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": [
                    "autoscaling:DescribeAutoScalingGroups",
                    "autoscaling:DescribeAutoScalingInstances",
                    "autoscaling:DescribeLaunchConfigurations",
                    "autoscaling:DescribeTags",
                    "autoscaling:SetDesiredCapacity",
                    "autoscaling:TerminateInstanceInAutoScalingGroup"
                ],
                "Resource": "*"
            }

            # Attach the necessary permissions
            clusterautoscaler_service_account.add_to_policy(iam.PolicyStatement.from_json(clusterautoscaler_policy_statement_json_1))

            # Install the Cluster Autoscaler
            # For more info see https://github.com/kubernetes/autoscaler
            clusterautoscaler_chart = eks_cluster.add_helm_chart(
                "cluster-autoscaler",
                chart="cluster-autoscaler",
                version="9.9.2",
                release="clusterautoscaler",
                repository="https://kubernetes.github.io/autoscaler",
                namespace="kube-system",
                values={
                    "autoDiscovery": {
                        "clusterName": eks_cluster.cluster_name
                    },
                    "awsRegion": self.region,
                    "rbac": {
                        "serviceAccount": {
                            "create": False,
                            "name": "clusterautoscaler"
                        }
                    },
                    "replicaCount": 2,
                    "extraArgs": {
                        "skip-nodes-with-system-pods": False,
                        "balance-similar-node-groups": True
                    }
                }
            )
            clusterautoscaler_chart.node.add_dependency(clusterautoscaler_service_account)
        
        # Deploy a managed Amazon Elasticsearch and a fluent-bit to ship our container logs there
        if (self.node.try_get_context("deploy_managed_elasticsearch") == "True"):
            # Create a new ElasticSearch Domain
            # NOTE: I changed this to a removal_policy of DESTROY to help cleanup while I was 
            # developing/iterating on the project. If you comment out that line it defaults to keeping 
            # the Domain upon deletion of the CloudFormation stack so you won't lose your log data
            
            # The capacity in Nodes and Volume Size/Type for the AWS Elasticsearch
            es_capacity = es.CapacityConfig(
                data_nodes=self.node.try_get_context("es_data_nodes"),
                data_node_instance_type=self.node.try_get_context("es_data_node_instance_type"),
                master_nodes=self.node.try_get_context("es_master_nodes"),
                master_node_instance_type=self.node.try_get_context("es_master_node_instance_type")
            )
            es_ebs = es.EbsOptions(
                enabled=True,
                volume_type=ec2.EbsDeviceVolumeType.GP2,
                volume_size=self.node.try_get_context("es_ebs_volume_size")
            )

            es_access_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": "es:*",
                "Principal": {
                    "AWS": "*"
                },
                "Resource": "*"
            }

            # Create SecurityGroup for Elastic
            elastic_security_group = ec2.SecurityGroup(
                self, "ElasticSecurityGroup",
                vpc=eks_vpc,
                allow_all_outbound=True
            )
            # Add a rule to allow our new SG to talk to the EKS control plane
            eks_cluster.cluster_security_group.add_ingress_rule(
                elastic_security_group,
                ec2.Port.all_traffic()
            )
            # Add a rule to allow the EKS control plane to talk to our new SG
            elastic_security_group.add_ingress_rule(
                eks_cluster.cluster_security_group,
                ec2.Port.all_traffic()
            )

            # Note that this AWS Elasticsearch domain is optimised for cost rather than availability
            # and defaults to one node in a single availability zone
            es_domain = es.Domain(
                self, "ESDomain",
                removal_policy=core.RemovalPolicy.DESTROY,
                version=es.ElasticsearchVersion.V7_9,
                vpc=eks_vpc,
                vpc_subnets=[ec2.SubnetSelection(subnets=[eks_vpc.private_subnets[0]])],
                security_groups=[elastic_security_group],
                capacity=es_capacity,
                ebs=es_ebs,
                access_policies=[iam.PolicyStatement.from_json(es_access_policy_statement_json_1)]
            )
            
            # Create the Service Account
            fluentbit_service_account = eks_cluster.add_service_account(
                "fluentbit",
                name="fluentbit",
                namespace="kube-system"
            )

            fluentbit_policy_statement_json_1 = {
            "Effect": "Allow",
                "Action": [
                    "es:ESHttp*"
                ],
                "Resource": [
                    es_domain.domain_arn
                ]
            }

            # Add the policies to the service account
            fluentbit_service_account.add_to_policy(iam.PolicyStatement.from_json(fluentbit_policy_statement_json_1))
            es_domain.grant_write(fluentbit_service_account)

            # For more info check out https://github.com/fluent/helm-charts/tree/main/charts/fluent-bit
            fluentbit_chart = eks_cluster.add_helm_chart(
                "fluentbit",
                chart="fluent-bit",
                version="0.15.15",
                release="fluent-bit",
                repository="https://fluent.github.io/helm-charts",
                namespace="kube-system",
                values={
                    "serviceAccount": {
                        "create": False,
                        "name": "fluentbit"
                    },
                    "config": {
                        "outputs": "[OUTPUT]\n    Name            es\n    Match           *\n    AWS_Region      "+self.region+"\n    AWS_Auth        On\n    Host            "+es_domain.domain_endpoint+"\n    Port            443\n    TLS             On\n    Replace_Dots    On\n"
                    }
                }
            )
            fluentbit_chart.node.add_dependency(fluentbit_service_account)

            # Output the Kibana address in our CloudFormation Stack
            core.CfnOutput(
                self, "KibanaAddress",
                value="https://" + es_domain.domain_endpoint + "/_plugin/kibana/",
                description="Private endpoint for this EKS environment's Kibana to consume the logs",

            )

        # Deploy Prometheus and Grafana
        if (self.node.try_get_context("deploy_kube_prometheus_operator") == "True"):
            # TODO Replace this with the new AWS Managed Prometheus and Grafana when it is Generally Available (GA)
            # For more information see https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack
            prometheus_chart = eks_cluster.add_helm_chart(
                "metrics",
                chart="kube-prometheus-stack",
                version="16.12.0",
                release="prometheus",
                repository="https://prometheus-community.github.io/helm-charts",
                namespace="kube-system",
                values={
                    "prometheus": {
                        "prometheusSpec": {
                        "storageSpec": {
                            "volumeClaimTemplate": {
                            "spec": {
                                "accessModes": [
                                "ReadWriteOnce"
                                ],
                                "resources": {
                                "requests": {
                                    "storage": self.node.try_get_context("prometheus_disk_size")
                                }
                                },
                                "storageClassName": "gp2"
                            }
                            }
                        }
                        }
                    },
                    "alertmanager": {
                        "alertmanagerSpec": {
                        "storage": {
                            "volumeClaimTemplate": {
                            "spec": {
                                "accessModes": [
                                "ReadWriteOnce"
                                ],
                                "resources": {
                                "requests": {
                                    "storage": self.node.try_get_context("alertmanager_disk_size")
                                }
                                },
                                "storageClassName": "gp2"
                            }
                            }
                        }
                        }
                    },
                    "grafana": {
                        "persistence": {
                            "enabled": "true",
                            "storageClassName": "gp2",
                            "size": self.node.try_get_context("grafana_disk_size")
                        }
                    }
                }          
            )

            # Deploy an internal NLB to Grafana
            grafananlb_manifest = eks_cluster.add_manifest("GrafanaNLB",{
                "kind": "Service",
                "apiVersion": "v1",
                "metadata": {
                    "name": "grafana-nlb",
                    "namespace": "kube-system",
                    "annotations": {
                        "service.beta.kubernetes.io/aws-load-balancer-type": "nlb-ip",
                        "service.beta.kubernetes.io/aws-load-balancer-internal": "true"
                    }
                },
                "spec": {
                    "ports": [
                    {
                        "name": "service",
                        "protocol": "TCP",
                        "port": 80,
                        "targetPort": 3000
                    }
                    ],
                    "selector": {
                        "app.kubernetes.io/name": "grafana"
                    },
                    "type": "LoadBalancer"
                }
            })

        # Install the metrics-server (required for the HPA)
        if (self.node.try_get_context("deploy_metrics_server") == "True"):
            # For more info see https://github.com/bitnami/charts/tree/master/bitnami/metrics-server
            metricsserver_chart = eks_cluster.add_helm_chart(
                "metrics-server",
                chart="metrics-server",
                version="5.9.1",
                release="metricsserver",
                repository="https://charts.bitnami.com/bitnami",
                namespace="kube-system",
                values={
                    "replicas": 2,
                    "apiService": {
                        "create": True
                    }
                }
            )

        # Install Calico to enforce NetworkPolicies
        if (self.node.try_get_context("deploy_calico_np") == "True"):
            # For more info see https://docs.aws.amazon.com/eks/latest/userguide/calico.html 
            # and https://github.com/aws/amazon-vpc-cni-k8s/tree/master/charts/aws-calico

            # First we need to install the CRDs which are not part of the Chart
            calico_crds_manifest_1 = eks_cluster.add_manifest("CalicoCRDManifest1",            
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "felixconfigurations.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "FelixConfiguration",
                    "plural": "felixconfigurations",
                    "singular": "felixconfiguration"
                    }
                }
                })
            calico_crds_manifest_2 = eks_cluster.add_manifest("CalicoCRDManifest2",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "ipamblocks.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "IPAMBlock",
                    "plural": "ipamblocks",
                    "singular": "ipamblock"
                    }
                }
                })
            calico_crds_manifest_3 = eks_cluster.add_manifest("CalicoCRDManifest3",            
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "blockaffinities.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "BlockAffinity",
                    "plural": "blockaffinities",
                    "singular": "blockaffinity"
                    }
                }
                })
            calico_crds_manifest_4 = eks_cluster.add_manifest("CalicoCRDManifest4",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "bgpconfigurations.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "BGPConfiguration",
                    "plural": "bgpconfigurations",
                    "singular": "bgpconfiguration"
                    }
                }
                })
            calico_crds_manifest_5 = eks_cluster.add_manifest("CalicoCRDManifest5",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "bgppeers.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "BGPPeer",
                    "plural": "bgppeers",
                    "singular": "bgppeer"
                    }
                }
                })
            calico_crds_manifest_6 = eks_cluster.add_manifest("CalicoCRDManifest6",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "ippools.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "IPPool",
                    "plural": "ippools",
                    "singular": "ippool"
                    }
                }
                })
            calico_crds_manifest_7 = eks_cluster.add_manifest("CalicoCRDManifest7",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "hostendpoints.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "HostEndpoint",
                    "plural": "hostendpoints",
                    "singular": "hostendpoint"
                    }
                }
                })
            calico_crds_manifest_8 = eks_cluster.add_manifest("CalicoCRDManifest8",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "clusterinformations.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "ClusterInformation",
                    "plural": "clusterinformations",
                    "singular": "clusterinformation"
                    }
                }
                })
            calico_crds_manifest_9 = eks_cluster.add_manifest("CalicoCRDManifest9",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "globalnetworkpolicies.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "GlobalNetworkPolicy",
                    "plural": "globalnetworkpolicies",
                    "singular": "globalnetworkpolicy"
                    }
                }
                })
            calico_crds_manifest_10 = eks_cluster.add_manifest("CalicoCRDManifest10",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "globalnetworksets.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Cluster",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "GlobalNetworkSet",
                    "plural": "globalnetworksets",
                    "singular": "globalnetworkset"
                    }
                }
                })
            calico_crds_manifest_11 = eks_cluster.add_manifest("CalicoCRDManifest11",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "networkpolicies.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Namespaced",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "NetworkPolicy",
                    "plural": "networkpolicies",
                    "singular": "networkpolicy"
                    }
                }
                })
            calico_crds_manifest_12 = eks_cluster.add_manifest("CalicoCRDManifest12",
                {
                "apiVersion": "apiextensions.k8s.io/v1beta1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": "networksets.crd.projectcalico.org"
                },
                "spec": {
                    "scope": "Namespaced",
                    "group": "crd.projectcalico.org",
                    "versions": [
                    {
                        "name": "v1",
                        "served": True,
                        "storage": True
                    }
                    ],
                    "names": {
                    "kind": "NetworkSet",
                    "plural": "networksets",
                    "singular": "networkset"
                    }
                }
                })
            # Then we can install the Helm Chart
            calico_np_chart = eks_cluster.add_helm_chart(
                "calico",
                chart="aws-calico",
                version="0.3.4",
                release="calico",
                repository="https://aws.github.io/eks-charts",
                namespace="kube-system"
            )
            # The Helm Chart depends on all the CRDs
            calico_np_chart.node.add_dependency(calico_crds_manifest_1)
            calico_np_chart.node.add_dependency(calico_crds_manifest_2)
            calico_np_chart.node.add_dependency(calico_crds_manifest_3)
            calico_np_chart.node.add_dependency(calico_crds_manifest_4)
            calico_np_chart.node.add_dependency(calico_crds_manifest_5)
            calico_np_chart.node.add_dependency(calico_crds_manifest_6)
            calico_np_chart.node.add_dependency(calico_crds_manifest_7)
            calico_np_chart.node.add_dependency(calico_crds_manifest_8)
            calico_np_chart.node.add_dependency(calico_crds_manifest_9)
            calico_np_chart.node.add_dependency(calico_crds_manifest_10)
            calico_np_chart.node.add_dependency(calico_crds_manifest_11)
            calico_np_chart.node.add_dependency(calico_crds_manifest_12)

        # Deploy SSM Agent
        if (self.node.try_get_context("deploy_ssm_agent") == "True"):
            # For more information see https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/install-ssm-agent-on-amazon-eks-worker-nodes-by-using-kubernetes-daemonset.html
            ssm_agent_manifest = eks_cluster.add_manifest("SSMAgentManifest",
            {
                "apiVersion":"apps/v1",
                "kind":"DaemonSet",
                "metadata":{
                    "labels":{
                        "k8s-app":"ssm-installer"
                    },
                    "name":"ssm-installer",
                    "namespace":"kube-system"
                },
                "spec":{
                    "selector":{
                        "matchLabels":{
                            "k8s-app":"ssm-installer"
                        }
                    },
                    "template":{
                        "metadata":{
                            "labels":{
                            "k8s-app":"ssm-installer"
                            }
                        },
                        "spec":{
                            "containers":[
                            {
                                "image":"amazonlinux",
                                "imagePullPolicy":"Always",
                                "name":"ssm",
                                "command":[
                                    "/bin/bash"
                                ],
                                "args":[
                                    "-c",
                                    "echo '* * * * * root yum install -y https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/linux_amd64/amazon-ssm-agent.rpm & rm -rf /etc/cron.d/ssmstart' > /etc/cron.d/ssmstart"
                                ],
                                "securityContext":{
                                    "allowPrivilegeEscalation":True
                                },
                                "volumeMounts":[
                                    {
                                        "mountPath":"/etc/cron.d",
                                        "name":"cronfile"
                                    }
                                ],
                                "terminationMessagePath":"/dev/termination-log",
                                "terminationMessagePolicy":"File"
                            }
                            ],
                            "volumes":[
                            {
                                "name":"cronfile",
                                "hostPath":{
                                    "path":"/etc/cron.d",
                                    "type":"Directory"
                                }
                            }
                            ],
                            "dnsPolicy":"ClusterFirst",
                            "restartPolicy":"Always",
                            "schedulerName":"default-scheduler",
                            "terminationGracePeriodSeconds":30
                        }
                    }
                }
            })

        # If you have a 'True' in the deploy_bastion variable at the top of the file we'll deploy
        # a basion server that you can connect to via Systems Manager Session Manager
        if (self.node.try_get_context("deploy_bastion") == "True"):
            # Create an Instance Profile for our Admin Role to assume w/EC2
            cluster_admin_role_instance_profile = iam.CfnInstanceProfile(
                self, "ClusterAdminRoleInstanceProfile",
                roles=[cluster_admin_role.role_name]
            )

            # Another way into our Bastion is via Systems Manager Session Manager
            if (self.node.try_get_context("create_new_cluster_admin_role") == "True"):
                cluster_admin_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))

            # Create Bastion
            # Get Latest Amazon Linux AMI
            amzn_linux = ec2.MachineImage.latest_amazon_linux(
                generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2,
                edition=ec2.AmazonLinuxEdition.STANDARD,
                virtualization=ec2.AmazonLinuxVirt.HVM,
                storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE
                )

            # Create SecurityGroup for bastion
            bastion_security_group = ec2.SecurityGroup(
                self, "BastionSecurityGroup",
                vpc=eks_vpc,
                allow_all_outbound=True
            )

            # Add a rule to allow our new SG to talk to the EKS control plane
            eks_cluster.cluster_security_group.add_ingress_rule(
                bastion_security_group,
                ec2.Port.all_traffic()
            )

            # Create our EC2 instance for bastion
            bastion_instance = ec2.Instance(
                self, "BastionInstance",
                instance_type=ec2.InstanceType(self.node.try_get_context("bastion_node_type")),
                machine_image=amzn_linux,
                role=cluster_admin_role,
                vpc=eks_vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                security_group=bastion_security_group,
                block_devices=[ec2.BlockDevice(device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(self.node.try_get_context("bastion_disk_size")))],
                key_name=self.node.try_get_context("eks_ssh_key")
            )

            # Set up our kubectl and fluxctl
            bastion_instance.user_data.add_commands("curl -o kubectl https://amazon-eks.s3.us-west-2.amazonaws.com/1.20.4/2021-04-12/bin/linux/amd64/kubectl")
            bastion_instance.user_data.add_commands("chmod +x ./kubectl")
            bastion_instance.user_data.add_commands("mv ./kubectl /usr/bin")
            bastion_instance.user_data.add_commands("aws eks update-kubeconfig --name " + eks_cluster.cluster_name + " --region " + self.region)
            bastion_instance.user_data.add_commands("curl -o fluxctl https://github.com/fluxcd/flux/releases/download/1.22.1/fluxctl_linux_amd64")
            bastion_instance.user_data.add_commands("chmod +x ./fluxctl")
            bastion_instance.user_data.add_commands("mv ./fluxctl /usr/bin")
            bastion_instance.user_data.add_commands("curl --silent --location https://rpm.nodesource.com/setup_14.x | bash -")
            bastion_instance.user_data.add_commands("yum install nodejs git -y")

            # Wait to deploy Bastion until cluster is up and we're deploying manifests/charts to it
            # This could be any of the charts/manifests I just picked this one at random
            bastion_instance.node.add_dependency(ssm_agent_manifest)


        if (self.node.try_get_context("deploy_client_vpn") == "True"):
            # Create and upload your client and server certs as per https://docs.aws.amazon.com/vpn/latest/clientvpn-admin/client-authentication.html#mutual
            # And then put the ARNs for them into the items below
            client_cert = cm.Certificate.from_certificate_arn(
                self, "ClientCert",
                certificate_arn=self.node.try_get_context("vpn_client_certificate_arn"))
            server_cert = cm.Certificate.from_certificate_arn(
                self, "ServerCert",
                certificate_arn=self.node.try_get_context("vpn_server_certificate_arn"))

            # Create SecurityGroup for VPN
            vpn_security_group = ec2.SecurityGroup(
                self, "VPNSecurityGroup",
                vpc=eks_vpc,
                allow_all_outbound=True
            )
            # Add a rule to allow our new SG to talk to the EKS control plane
            eks_cluster.cluster_security_group.add_ingress_rule(
                vpn_security_group,
                ec2.Port.all_traffic()
            )

            if (self.node.try_get_context("deploy_managed_elasticsearch") == "True"):
                # Add a rule to allow our new SG to talk to Elastic
                elastic_security_group.add_ingress_rule(
                    vpn_security_group,
                    ec2.Port.all_traffic()
                )

            # Create CloudWatch Log Group and Stream and keep the logs for 1 month
            log_group = logs.LogGroup(
                self, "VPNLogGroup",
                retention=logs.RetentionDays.ONE_MONTH
            )
            log_stream = log_group.add_stream("VPNLogStream")

            endpoint = ec2.CfnClientVpnEndpoint(
                self, "VPNEndpoint",
                description="EKS Client VPN",
                authentication_options=[{
                    "type": "certificate-authentication",
                    "mutualAuthentication": {
                        "clientRootCertificateChainArn": client_cert.certificate_arn
                    }
                }],
                client_cidr_block=self.node.try_get_context("vpn_client_cidr_block"),
                server_certificate_arn=server_cert.certificate_arn,
                connection_log_options={
                    "enabled": True,
                    "cloudwatchLogGroup": log_group.log_group_name,
                    "cloudwatchLogStream": log_stream.log_stream_name
                },
                split_tunnel=True,
                security_group_ids=[vpn_security_group.security_group_id],
                vpc_id=eks_vpc.vpc_id
            )

            ec2.CfnClientVpnAuthorizationRule(
                self, "ClientVpnAuthRule",
                client_vpn_endpoint_id=endpoint.ref,
                target_network_cidr=eks_vpc.vpc_cidr_block,
                authorize_all_groups=True,
                description="Authorize the Client VPN access to our VPC CIDR"
            )

            ec2.CfnClientVpnTargetNetworkAssociation(
                self, "ClientVpnNetworkAssociation",
                client_vpn_endpoint_id=endpoint.ref,
                subnet_id=eks_vpc.private_subnets[0].subnet_id
            )

        # Enable control plane logging which requires a Custom Resource until it has proper
        # CloudFormation support that CDK can leverage
        EKSLogsObjectResource(
            self, "EKSLogsObjectResource",
            eks_name=eks_cluster.cluster_name,
            eks_arn=eks_cluster.cluster_arn
        )

        # Install the OPA Gatekeeper
        if (self.node.try_get_context("deploy_opa_gatekeeper") == "True"):
            # For more info see https://github.com/open-policy-agent/gatekeeper
            gatekeeper_chart = eks_cluster.add_helm_chart(
                "gatekeeper",
                chart="gatekeeper",
                version="3.6.0-beta.2",
                release="gatekeeper",
                repository="https://open-policy-agent.github.io/gatekeeper/charts",
                namespace="kube-system"
            )

        if (self.node.try_get_context("deploy_gatekeeper_policies") == "True"):
            # For more info see https://github.com/aws-quickstart/quickstart-eks-cdk-python/tree/main/gatekeeper-policies
            # and https://github.com/fluxcd/flux/tree/master/chart/flux
            flux_gatekeeper_chart = eks_cluster.add_helm_chart(
                "flux-gatekeeper",
                chart="flux",
                version="1.10.0",
                release="flux-gatekeeper",
                repository="https://charts.fluxcd.io",
                namespace="kube-system",
                values={
                    "git": {
                        "url": self.node.try_get_context("gatekeeper_policies_git_url"),
                        "branch": self.node.try_get_context("gatekeeper_policies_git_branch"),
                        "path": self.node.try_get_context("gatekeeper_policies_git_path")
                    }
                }
            )

app = core.App()
if app.node.try_get_context("account").strip() != "":
    account = app.node.try_get_context("account")
else:
    account = os.environ.get("CDK_DEPLOY_ACCOUNT", os.environ["CDK_DEFAULT_ACCOUNT"])

if app.node.try_get_context("region").strip() != "":
    region = app.node.try_get_context("region")
else:
    region = os.environ.get("CDK_DEPLOY_REGION", os.environ["CDK_DEFAULT_REGION"])
# Note that if we didn't pass through the ACCOUNT and REGION from these environment variables that
# it won't let us create 3 AZs and will only create a max of 2 - even when we ask for 3 in eks_vpc
eks_cluster_stack = EKSClusterStack(app, "EKSClusterStack", env=core.Environment(account=account, region=region))
app.synth()
