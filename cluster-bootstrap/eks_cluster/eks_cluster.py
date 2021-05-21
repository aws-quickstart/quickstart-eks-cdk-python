"""
Purpose

Example of how to provision an EKS cluster, create the IAM Roles for Service Accounts (IRSA) mappings,
and then deploy various required cluster add-ons (AWS LB Controller, ExternalDNS, Prometheus/Grafana,
AWS Elasticsearch, etc.)
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
from aws_cdk.core import PhysicalName

from ekslogs_custom_resource import EKSLogsObjectResource

class EKSClusterStack(core.Stack):

    def set_cluster_role(self, cdk_context):
        # Either create a new IAM role to administrate the cluster or create a new one
        if cdk_context["create_new_cluster_admin_role"]:
            cluster_admin_role = iam.Role(self, id="ClusterAdminRole", assumed_by=
            iam.CompositePrincipal(iam.ServicePrincipal("eks.amazonaws.com"), iam.AccountRootPrincipal()),
                                          description="EKS Cluster Admin Role Controller",
                                          managed_policies=[
                                              iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEKSServicePolicy'),
                                              iam.ManagedPolicy.from_aws_managed_policy_name('AmazonEKSClusterPolicy')
                                          ],
                                          role_name=PhysicalName.GENERATE_IF_NEEDED)

        else:
            # You'll also need to add a trust relationship to ec2.amazonaws.com to sts:AssumeRole to this as well
            cluster_admin_role = iam.Role.from_role_arn(self, "ClusterAdminRole",
                                                        role_arn=cdk_context["existing_role_arn"])
        return cluster_admin_role

    def create_vpc(self, cdk_context):
        # Either create a new VPC with the options below OR import an existing one by name
        if cdk_context["create_new_vpc"]:
            eks_vpc = ec2.Vpc(
                self, "VPC",
                # We are choosing to spread our VPC across 3 availability zones
                max_azs=3,
                # We are creating a VPC that has a /22, 1024 IPs, for our EKS cluster.
                # I am using that instead of a /16 etc. as I know many companies have constraints here
                # If you can go bigger than this great - but I would try not to go much smaller if you can
                # I use https://www.davidc.net/sites/default/subnets/subnets.html to me work out the CIDRs
                cidr=cdk_context["vpc_cidr"],
                subnet_configuration=[
                    # 3 x Public Subnets (1 per AZ) with 64 IPs each for our ALBs and NATs
                    ec2.SubnetConfiguration(
                        subnet_type=ec2.SubnetType.PUBLIC,
                        name="Public",
                        cidr_mask=cdk_context["vpc_cidr_mask_public"]
                    ),
                    # 3 x Private Subnets (1 per AZ) with 256 IPs each for our Nodes and Pods
                    ec2.SubnetConfiguration(
                        subnet_type=ec2.SubnetType.PRIVATE,
                        name="Private",
                        cidr_mask=cdk_context["vpc_cidr_mask_private"]
                    )
                ]
            )
        else:
            eks_vpc = ec2.Vpc.from_lookup(self, 'VPC', vpc_name=cdk_context["existing_vpc_name"])

        return eks_vpc

    def create_alb_policies(self):
        # Create the PolicyStatements to attach to the role
        # I couldn't find a way to get this to work with a whole PolicyDocument and there are 10 statements
        # TODO this should be refactored. Moving outside main constructor for now.

        alb_policy = {}
        alb_policy_statement_json_1 = {
            "Effect": "Allow",
            "Action": [
                "acm:DescribeCertificate",
                "acm:ListCertificates",
                "acm:GetCertificate"
            ],
            "Resource": "*"
        }
        alb_policy["alb_policy_statement_json_1"] = alb_policy_statement_json_1

        alb_policy_statement_json_2 = {
            "Effect": "Allow",
            "Action": [
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:CreateSecurityGroup",
                "ec2:CreateTags",
                "ec2:DeleteTags",
                "ec2:DeleteSecurityGroup",
                "ec2:DescribeAccountAttributes",
                "ec2:DescribeAddresses",
                "ec2:DescribeInstances",
                "ec2:DescribeInstanceStatus",
                "ec2:DescribeInternetGateways",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeSubnets",
                "ec2:DescribeTags",
                "ec2:DescribeVpcs",
                "ec2:ModifyInstanceAttribute",
                "ec2:ModifyNetworkInterfaceAttribute",
                "ec2:RevokeSecurityGroupIngress"
            ],
            "Resource": "*"
        }
        alb_policy["alb_policy_statement_json_2"] = alb_policy_statement_json_2

        alb_policy_statement_json_3 = {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:AddListenerCertificates",
                "elasticloadbalancing:AddTags",
                "elasticloadbalancing:CreateListener",
                "elasticloadbalancing:CreateLoadBalancer",
                "elasticloadbalancing:CreateRule",
                "elasticloadbalancing:CreateTargetGroup",
                "elasticloadbalancing:DeleteListener",
                "elasticloadbalancing:DeleteLoadBalancer",
                "elasticloadbalancing:DeleteRule",
                "elasticloadbalancing:DeleteTargetGroup",
                "elasticloadbalancing:DeregisterTargets",
                "elasticloadbalancing:DescribeListenerCertificates",
                "elasticloadbalancing:DescribeListeners",
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeLoadBalancerAttributes",
                "elasticloadbalancing:DescribeRules",
                "elasticloadbalancing:DescribeSSLPolicies",
                "elasticloadbalancing:DescribeTags",
                "elasticloadbalancing:DescribeTargetGroups",
                "elasticloadbalancing:DescribeTargetGroupAttributes",
                "elasticloadbalancing:DescribeTargetHealth",
                "elasticloadbalancing:ModifyListener",
                "elasticloadbalancing:ModifyLoadBalancerAttributes",
                "elasticloadbalancing:ModifyRule",
                "elasticloadbalancing:ModifyTargetGroup",
                "elasticloadbalancing:ModifyTargetGroupAttributes",
                "elasticloadbalancing:RegisterTargets",
                "elasticloadbalancing:RemoveListenerCertificates",
                "elasticloadbalancing:RemoveTags",
                "elasticloadbalancing:SetIpAddressType",
                "elasticloadbalancing:SetSecurityGroups",
                "elasticloadbalancing:SetSubnets",
                "elasticloadbalancing:SetWebAcl"
            ],
            "Resource": "*"
        }

        alb_policy["alb_policy_statement_json_3"] = alb_policy_statement_json_3

        alb_policy_statement_json_4 = {
            "Effect": "Allow",
            "Action": [
                "iam:CreateServiceLinkedRole",
                "iam:GetServerCertificate",
                "iam:ListServerCertificates"
            ],
            "Resource": "*"
        }

        alb_policy["alb_policy_statement_json_4"] = alb_policy_statement_json_4

        alb_policy_statement_json_5 = {
            "Effect": "Allow",
            "Action": [
                "cognito-idp:DescribeUserPoolClient"
            ],
            "Resource": "*"
        }
        alb_policy["alb_policy_statement_json_5"] = alb_policy_statement_json_5

        alb_policy_statement_json_6 = {
            "Effect": "Allow",
            "Action": [
                "waf-regional:GetWebACLForResource",
                "waf-regional:GetWebACL",
                "waf-regional:AssociateWebACL",
                "waf-regional:DisassociateWebACL"
            ],
            "Resource": "*"
        }

        alb_policy["alb_policy_statement_json_6"] = alb_policy_statement_json_6

        alb_policy_statement_json_7 = {
            "Effect": "Allow",
            "Action": [
                "tag:GetResources",
                "tag:TagResources"
            ],
            "Resource": "*"
        }
        alb_policy["alb_policy_statement_json_7"] = alb_policy_statement_json_7

        alb_policy_statement_json_8 = {
            "Effect": "Allow",
            "Action": [
                "waf:GetWebACL"
            ],
            "Resource": "*"
        }
        alb_policy["alb_policy_statement_json_8"] = alb_policy_statement_json_8

        alb_policy_statement_json_9 = {
            "Effect": "Allow",
            "Action": [
                "wafv2:GetWebACL",
                "wafv2:GetWebACLForResource",
                "wafv2:AssociateWebACL",
                "wafv2:DisassociateWebACL"
            ],
            "Resource": "*"
        }

        alb_policy["alb_policy_statement_json_9"] = alb_policy_statement_json_9

        alb_policy_statement_json_10 = {
            "Effect": "Allow",
            "Action": [
                "shield:DescribeProtection",
                "shield:GetSubscriptionState",
                "shield:DeleteProtection",
                "shield:CreateProtection",
                "shield:DescribeSubscription",
                "shield:ListProtections"
            ],
            "Resource": "*"
        }
        alb_policy["alb_policy_statement_json_10"] = alb_policy_statement_json_10
        return alb_policy

    def awsebscsidriver_policy_statement(self):
        # Create the PolicyStatements to attach to the role
        # TODO This needs to be cleaned up.
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
        return awsebscsidriver_policy_statement_json_1

    def awsefscsidriver_policy(self):
        # Create the PolicyStatements to attach to the role
        # TODO This needs to be cleaned up.

        awsefscsidriver_policy = {}
        awsefscsidriver_policy_statement_json_1 = {
            "Effect": "Allow",
            "Action": [
                "elasticfilesystem:DescribeAccessPoints",
                "elasticfilesystem:DescribeFileSystems"
            ],
            "Resource": "*"
        }
        awsefscsidriver_policy["awsefscsidriver_policy_statement_json_1"] = awsefscsidriver_policy_statement_json_1

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
        awsefscsidriver_policy["awsefscsidriver_policy_statement_json_2"] = awsefscsidriver_policy_statement_json_2

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
        awsefscsidriver_policy["awsefscsidriver_policy_statement_json_3"] = awsefscsidriver_policy_statement_json_3

        return awsefscsidriver_policy

    def create_calico_manifests(self):
        calico_manifest = {}
        # TODO these manifest are all the same.  Probably can be cleaned up further
        CalicoCRDManifest1 = {
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
        }

        calico_manifest["CalicoCRDManifest1"] = CalicoCRDManifest1
        CalicoCRDManifest2 = {
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
        }

        calico_manifest["CalicoCRDManifest2"] = CalicoCRDManifest2
        CalicoCRDManifest3 = {
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
        }

        calico_manifest["CalicoCRDManifest3"] = CalicoCRDManifest3
        CalicoCRDManifest4 = {
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
        }

        calico_manifest["CalicoCRDManifest4"] = CalicoCRDManifest4
        CalicoCRDManifest5 = {
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
        }

        calico_manifest["CalicoCRDManifest5"] = CalicoCRDManifest5

        CalicoCRDManifest6 = {
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
        }
        calico_manifest["CalicoCRDManifest6"] = CalicoCRDManifest6

        CalicoCRDManifest7 = {
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
        }
        calico_manifest["CalicoCRDManifest7"] = CalicoCRDManifest7
        CalicoCRDManifest8 = {
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
        }
        calico_manifest["CalicoCRDManifest8"] = CalicoCRDManifest8

        CalicoCRDManifest9 = {
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
        }
        calico_manifest["CalicoCRDManifest9"] = CalicoCRDManifest9

        CalicoCRDManifest10 = {
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
        }

        calico_manifest["CalicoCRDManifest10"] = CalicoCRDManifest10
        CalicoCRDManifest11 = {
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
        }
        calico_manifest["CalicoCRDManifest11"] = CalicoCRDManifest11

        CalicoCRDManifest12 = {
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
        }
        calico_manifest["CalicoCRDManifest12"] = CalicoCRDManifest12
        return calico_manifest


    def __init__(self, scope: core.Construct, id: str, cdk_context, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        cluster_admin_role = self.set_cluster_role(cdk_context)
        eks_vpc = self.create_vpc(cdk_context)

        # Create an EKS Cluster
        eks_cluster = eks.Cluster(
            self, "cluster",
            vpc=eks_vpc,
            masters_role=cluster_admin_role,
            # Make our cluster's control plane accessible only within our private VPC
            # This means that we'll have to ssh to a jumpbox/bastion or set up a VPN to manage it
            endpoint_access=eks.EndpointAccess.PRIVATE,
            version=cdk_context["eks_version"],
            default_capacity=0
        )

        # Add a Managed Node Group
        eks_node_group = eks_cluster.add_nodegroup_capacity(
            "cluster-default-ng",
            desired_size=cdk_context["eks_node_quantity"],
            disk_size=cdk_context["eks_node_disk_size"],
            # The default in CDK is to force upgrades through even if they violate - it is safer to not do that
            force_update=False,
            instance_types=[ec2.InstanceType(cdk_context["eks_node_type"])],
            release_version=cdk_context["eks_node_ami_version"]
        )
        eks_node_group.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))

        # AWS Load Balancer Controller
        if cdk_context["deploy_aws_lb_controller"]:
            alb_service_account = eks_cluster.add_service_account(
                "aws-load-balancer-controller",
                name="aws-load-balancer-controller",
                namespace="kube-system"
            )
            alb_policies = self.create_alb_policies()

            # Attach the necessary permissions
            for policy in alb_policies:
                alb_service_account.add_to_policy(iam.PolicyStatement.from_json(alb_policies[policy]))

            # Deploy the AWS Load Balancer Controller from the AWS Helm Chart
            # For more info check out https://github.com/aws/eks-charts/tree/master/stable/aws-load-balancer-controller
            awslbcontroller_chart = eks_cluster.add_helm_chart(
                "aws-load-balancer-controller",
                chart="aws-load-balancer-controller",
                version="1.1.5",
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
        if cdk_context["deploy_external_dns"]:
            externaldns_service_account = eks_cluster.add_service_account(
                "external-dns",
                name="external-dns",
                namespace="kube-system"
            )

            # Create the PolicyStatements to attach to the role
            # NOTE that this will give External DNS access to all Route53 zones
            # For production you'll likely want to replace 'Resourece *' with specific resources
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
            externaldns_service_account.add_to_policy(
                iam.PolicyStatement.from_json(externaldns_policy_statement_json_1))
            externaldns_service_account.add_to_policy(
                iam.PolicyStatement.from_json(externaldns_policy_statement_json_2))

            # Deploy External DNS from the bitnami Helm chart
            # For more info see https://github.com/bitnami/charts/tree/master/bitnami/external-dns
            externaldns_chart = eks_cluster.add_helm_chart(
                "external-dns",
                chart="external-dns",
                version="5.0.0",
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
        if cdk_context["deploy_aws_ebs_csi"]:
            awsebscsidriver_service_account = eks_cluster.add_service_account(
                "awsebscsidriver",
                name="awsebscsidriver",
                namespace="kube-system"
            )

            awsebscsidriver_policy_statement_json_1 = self.awsebscsidriver_policy_statement()
            # Attach the necessary permissions
            awsebscsidriver_service_account.add_to_policy(
                iam.PolicyStatement.from_json(awsebscsidriver_policy_statement_json_1))

            # Install the AWS EBS CSI Driver
            # For more info see https://github.com/kubernetes-sigs/aws-ebs-csi-driver
            awsebscsi_chart = eks_cluster.add_helm_chart(
                "aws-ebs-csi-driver",
                chart="aws-ebs-csi-driver",
                version="1.0.1",
                release="awsebscsidriver",
                repository="https://kubernetes-sigs.github.io/aws-ebs-csi-driver",
                namespace="kube-system",
                values={
                    "region": self.region,
                    "enableVolumeScheduling": True,
                    "enableVolumeResizing": True,
                    "enableVolumeSnapshot": True,
                    "serviceAccount": {
                        "controller": {
                            "create": False,
                            "name": "awsebscsidriver"
                        },
                        "snapshot": {
                            "create": False,
                            "name": "awsebscsidriver"
                        }
                    }
                }
            )
            awsebscsi_chart.node.add_dependency(awsebscsidriver_service_account)

        # AWS EFS CSI Driver
        if cdk_context["deploy_aws_efs_csi"]:
            awsefscsidriver_service_account = eks_cluster.add_service_account(
                "awsefscsidriver",
                name="awsefscsidriver",
                namespace="kube-system"
            )

            awsefscsidriver_policy = self.awsefscsidriver_policy()
            # Attach the necessary permissions
            for policy in awsefscsidriver_policy:
                awsefscsidriver_service_account.add_to_policy(
                    iam.PolicyStatement.from_json(awsefscsidriver_policy[policy]))

            # Install the AWS EFS CSI Driver
            # For more info see https://github.com/kubernetes-sigs/aws-efs-csi-driver
            awsefscsi_chart = eks_cluster.add_helm_chart(
                "aws-efs-csi-driver",
                chart="aws-efs-csi-driver",
                version="1.2.4",
                release="awsefscsidriver",
                repository="https://kubernetes-sigs.github.io/aws-efs-csi-driver/",
                namespace="kube-system",
                values={
                    "serviceAccount": {
                        "controller": {
                            "create": False,
                            "name": "awsefscsidriver"
                        }
                    }
                }
            )
            awsefscsi_chart.node.add_dependency(awsefscsidriver_service_account)

        # cluster-autoscaler
        if cdk_context["deploy_cluster_autoscaler"]:
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
            clusterautoscaler_service_account.add_to_policy(
                iam.PolicyStatement.from_json(clusterautoscaler_policy_statement_json_1))

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
                    "replicaCount": 2
                }
            )
            clusterautoscaler_chart.node.add_dependency(clusterautoscaler_service_account)

        # Deploy a managed Amazon Elasticsearch and a fluent-bit to ship our container logs there
        if cdk_context["deploy_managed_elasticsearch"]:
            # Create a new ElasticSearch Domain
            # NOTE: I changed this to a removal_policy of DESTROY to help cleanup while I was 
            # developing/iterating on the project. If you comment out that line it defaults to keeping 
            # the Domain upon deletion of the CloudFormation stack so you won't lose your log data
            es_access_policy_statement_json_1 = {
                "Effect": "Allow",
                "Action": "es:*",
                "Principal": {
                    "AWS": "*"
                },
                "Resource": "*"
            }
            # Note that this AWS Elasticsearch domain is optimised for cost rather than availability
            # and defaults to one node in a single availability zone
            # TODO move elasticSearch version to context
            es_domain = es.Domain(
                self, "ESDomain",
                removal_policy=core.RemovalPolicy.DESTROY,
                version=es.ElasticsearchVersion.V7_9,
                vpc=eks_vpc,
                vpc_subnets=[ec2.SubnetSelection(subnets=[eks_vpc.private_subnets[0]])],
                security_groups=[eks_cluster.cluster_security_group],
                capacity=cdk_context["es_capacity"],
                ebs=cdk_context["es_ebs"],
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
                version="0.15.8",
                release="fluent-bit",
                repository="https://fluent.github.io/helm-charts",
                namespace="kube-system",
                values={
                    "config": {
                        "outputs": "[OUTPUT]\n    Name            es\n    Match           *\n    AWS_Region      " + self.region + "\n    AWS_Auth        On\n    Host            " + es_domain.domain_endpoint + "\n    Port            443\n    TLS             On\n    Replace_Dots    On\n"
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
        if cdk_context["deploy_kube_prometheus_operator"]:
            # TODO Replace this with the new AWS Managed Prometheus and Grafana when it is Generally Available (GA)
            # For more information see https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack
            prometheus_chart = eks_cluster.add_helm_chart(
                "metrics",
                chart="kube-prometheus-stack",
                version="15.4.6",
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
                                                "storage": "8Gi"
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
                                                "storage": "2Gi"
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
                            "storageClassName": "gp2"
                        }
                    }
                }
            )

            # Deploy an internal NLB to Grafana
            grafananlb_manifest = eks_cluster.add_manifest("GrafanaNLB", {
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
        if cdk_context["deploy_metrics_server"]:
            # For more info see https://github.com/bitnami/charts/tree/master/bitnami/metrics-server
            metricsserver_chart = eks_cluster.add_helm_chart(
                "metrics-server",
                chart="metrics-server",
                version="5.8.7",
                release="metricsserver",
                repository="https://charts.bitnami.com/bitnami",
                namespace="kube-system",
                values={
                    "replicas": 2
                }
            )

        # Install the OPA Gatekeeper
        if cdk_context["deploy_opa_gatekeeper"]:
            # For more info see https://github.com/open-policy-agent/gatekeeper
            gatekeeper_chart = eks_cluster.add_helm_chart(
                "gatekeeper",
                chart="gatekeeper",
                version="3.4.0",
                release="gatekeeper",
                repository="https://open-policy-agent.github.io/gatekeeper/charts",
                namespace="kube-system"
            )

            # Gatekeeper being an admission controller needs to be deployed last to not interfere
            if metricsserver_chart is not None:
                gatekeeper_chart.node.add_dependency(metricsserver_chart)
            if clusterautoscaler_chart is not None:
                gatekeeper_chart.node.add_dependency(clusterautoscaler_chart)
            if awsebscsi_chart is not None:
                gatekeeper_chart.node.add_dependency(awsebscsi_chart)
            if awsefscsi_chart is not None:
                gatekeeper_chart.node.add_dependency(awsefscsi_chart)
            if grafananlb_manifest is not None:
                gatekeeper_chart.node.add_dependency(grafananlb_manifest)
            if prometheus_chart is not None:
                gatekeeper_chart.node.add_dependency(prometheus_chart)
            if fluentbit_chart is not None:
                gatekeeper_chart.node.add_dependency(fluentbit_chart)
            if externaldns_chart is not None:
                gatekeeper_chart.node.add_dependency(externaldns_chart)
            if awslbcontroller_chart is not None:
                gatekeeper_chart.node.add_dependency(awslbcontroller_chart)

        # Install the OPA Gatekeeper
        if cdk_context["deploy_calico_np"]:
            # For more info see https://docs.aws.amazon.com/eks/latest/userguide/calico.html 
            # and https://github.com/aws/amazon-vpc-cni-k8s/tree/master/charts/aws-calico

            # First we need to install the CRDs which are not part of the Chart

            # Then we can install the Helm Chart
            calico_np_chart = eks_cluster.add_helm_chart(
                "calico",
                chart="aws-calico",
                version="0.3.4",
                release="calico",
                repository="https://aws.github.io/eks-charts",
                namespace="kube-system"
            )

            calico_manifests = self.create_calico_manifests()
            for manifest in calico_manifests:
                calico_crds = eks_cluster.add_manifest(manifest,calico_manifests[manifest])
                # The Helm Chart depends on all the CRDs
                calico_np_chart.node.add_dependency(calico_crds)

        # Deploy SSM Agent
        if cdk_context["deploy_ssm_agent"]:
            # For more information see https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/install-ssm-agent-on-amazon-eks-worker-nodes-by-using-kubernetes-daemonset.html
            ssm_agent_manifest = eks_cluster.add_manifest("SSMAgentManifest",
                                                          {
                                                              "apiVersion": "apps/v1",
                                                              "kind": "DaemonSet",
                                                              "metadata": {
                                                                  "labels": {
                                                                      "k8s-app": "ssm-installer"
                                                                  },
                                                                  "name": "ssm-installer",
                                                                  "namespace": "kube-system"
                                                              },
                                                              "spec": {
                                                                  "selector": {
                                                                      "matchLabels": {
                                                                          "k8s-app": "ssm-installer"
                                                                      }
                                                                  },
                                                                  "template": {
                                                                      "metadata": {
                                                                          "labels": {
                                                                              "k8s-app": "ssm-installer"
                                                                          }
                                                                      },
                                                                      "spec": {
                                                                          "containers": [
                                                                              {
                                                                                  "image": "amazonlinux",
                                                                                  "imagePullPolicy": "Always",
                                                                                  "name": "ssm",
                                                                                  "command": [
                                                                                      "/bin/bash"
                                                                                  ],
                                                                                  "args": [
                                                                                      "-c",
                                                                                      "echo '* * * * * root yum install -y https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/linux_amd64/amazon-ssm-agent.rpm & rm -rf /etc/cron.d/ssmstart' > /etc/cron.d/ssmstart"
                                                                                  ],
                                                                                  "securityContext": {
                                                                                      "allowPrivilegeEscalation": True
                                                                                  },
                                                                                  "volumeMounts": [
                                                                                      {
                                                                                          "mountPath": "/etc/cron.d",
                                                                                          "name": "cronfile"
                                                                                      }
                                                                                  ],
                                                                                  "terminationMessagePath": "/dev/termination-log",
                                                                                  "terminationMessagePolicy": "File"
                                                                              }
                                                                          ],
                                                                          "volumes": [
                                                                              {
                                                                                  "name": "cronfile",
                                                                                  "hostPath": {
                                                                                      "path": "/etc/cron.d",
                                                                                      "type": "Directory"
                                                                                  }
                                                                              }
                                                                          ],
                                                                          "dnsPolicy": "ClusterFirst",
                                                                          "restartPolicy": "Always",
                                                                          "schedulerName": "default-scheduler",
                                                                          "terminationGracePeriodSeconds": 30
                                                                      }
                                                                  }
                                                              }
                                                          })

        # If you have a 'True' in the deploy_bastion variable at the top of the file we'll deploy
        # a basion server that you can connect to via Systems Manager Session Manager
        if cdk_context["deploy_bastion"]:
            # Create an Instance Profile for our Admin Role to assume w/EC2
            cluster_admin_role_instance_profile = iam.CfnInstanceProfile(
                self, "ClusterAdminRoleInstanceProfile",
                roles=[cluster_admin_role.role_name]
            )

            # Another way into our Bastion is via Systems Manager Session Manager
            if cdk_context["create_new_cluster_admin_role"]:
                cluster_admin_role.add_managed_policy(
                    iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"))

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
                instance_type=ec2.InstanceType(cdk_context["basiton_node_type"]),
                machine_image=amzn_linux,
                role=cluster_admin_role,
                vpc=eks_vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                security_group=bastion_security_group,
                block_devices=[ec2.BlockDevice(device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(cdk_context["basiton_disk_size"]))]
            )

            # Set up our kubectl and fluxctl
            bastion_instance.user_data.add_commands(
                "curl -o kubectl https://amazon-eks.s3.us-west-2.amazonaws.com/1.19.6/2021-01-05/bin/linux/amd64/kubectl")
            bastion_instance.user_data.add_commands("chmod +x ./kubectl")
            bastion_instance.user_data.add_commands("mv ./kubectl /usr/bin")
            bastion_instance.user_data.add_commands(
                "aws eks update-kubeconfig --name " + eks_cluster.cluster_name + " --region " + self.region)
            bastion_instance.user_data.add_commands(
                "curl -o fluxctl https://github.com/fluxcd/flux/releases/download/1.22.1/fluxctl_linux_amd64")
            bastion_instance.user_data.add_commands("chmod +x ./fluxctl")
            bastion_instance.user_data.add_commands("mv ./fluxctl /usr/bin")

            # Wait to deploy Bastion until cluster is up and we're deploying manifests/charts to it
            # This could be any of the charts/manifests I just picked this one at random
            bastion_instance.node.add_dependency(ssm_agent_manifest)

        if cdk_context["deploy_client_vpn"]:
            # Create and upload your client and server certs as per
            # https://docs.aws.amazon.com/vpn/latest/clientvpn-admin/client-authentication.html#mutual
            # And then put the ARNs for them into the items below
            client_cert = cm.Certificate.from_certificate_arn(
                self, "ClientCert",
                certificate_arn=cdk_context["client_certificate_arn"])
            server_cert = cm.Certificate.from_certificate_arn(
                self, "ServerCert",
                certificate_arn=cdk_context["server_certificate_arn"])

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
                client_cidr_block=cdk_context["vpn_client_cidr_block"],
                server_certificate_arn=server_cert.certificate_arn,
                connection_log_options={
                    "enabled": True,
                    "cloudwatchLogGroup": log_group.log_group_name,
                    "cloudwatchLogStream": log_stream.log_stream_name
                },
                split_tunnel=True,
                security_group_ids=[eks_cluster.cluster_security_group_id],
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

        if cdk_context["deploy_gatekeeper_policies"]:
            # For more info see https://github.com/aws-quickstart/quickstart-eks-cdk-python/tree/main/gatekeeper-policies
            flux_gatekeeper_chart = eks_cluster.add_helm_chart(
                "flux-gatekeeper",
                chart="flux",
                version="1.9.0",
                release="flux-gatekeeper",
                repository="https://charts.fluxcd.io",
                namespace="kube-system",
                values={
                    "git": {
                        "url": cdk_context["gatekeeper_policies_git_url"],
                        "branch": cdk_context["gatekeeper_policies_git_branch"],
                        "path": cdk_context["gatekeeper_policies_git_path"]
                    }
                }
            )
