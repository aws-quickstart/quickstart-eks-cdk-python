from aws_cdk import (
    aws_eks as eks,
    aws_elasticsearch as es,
    aws_ec2 as ec2
)


class Context:

    def set_eks_version(self, version):
        # EKS Control Plane version (this is part of the CDK EKS class e.g. eks.KubernetesVersion.V1_19)
        # It is an object not a string and VS Code etc. will autocomplete it for you when you type the dot
        # See https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_eks/KubernetesVersion.html
        if not version:
            eks_version = eks.KubernetesVersion.V1_19
        else:
            if version.strip() == "V1_19":
                eks_version = eks.KubernetesVersion.V1_19
            elif version.strip() == "V1.18":
                eks_version = eks.KubernetesVersion.V1_18
            elif version.strip() == "V1.17":
                eks_version = eks.KubernetesVersion.V1_17
            else:
                raise Exception("Invalid Kubernetes Version See "
                                "https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_eks/KubernetesVersion.html")
        return eks_version

    def set_ec2_ebs(self, diskdrive):
        if not diskdrive:
            ec2disk = ec2.EbsDeviceVolumeType.GP2
        elif "GP2":
            ec2disk = ec2.EbsDeviceVolumeType.GP2
        elif "GP3":
            ec2disk = ec2.EbsDeviceVolumeType.GP2
        else:
            ec2disk = ec2.EbsDeviceVolumeType.GP2
        return ec2disk

    def handle_property(self, str_value, property_value, message="Readme.MD", required=True):
        if not str_value.strip():
            if required:
                raise Exception(
                    "Property value " + property_value + " not set in cdk.json. See " + message + " for more information")
            else:
                return ""
        else:
            return str_value;

    def handle_property_default(self, str_value, property_value, default):
        if not str_value.strip():
            print("Property value " + property_value + " not set in cdk.json. Defaulting to " + str(default))
            return default
        elif str_value == "True":
            return True
        else:
            return False

    context = {}

    def __init__(self, app) -> None:
        self.context["account"] = self.handle_property(app.node.try_get_context("account"), "account", required=False)
        self.context["region"] = self.handle_property(app.node.try_get_context("region"), "region", required=False)
        self.context["eks_version"] = self.set_eks_version(app.node.try_get_context("eks_version"))
        # EKS Node Instance Type
        self.context["eks_node_type"] = self.handle_property(app.node.try_get_context("node_type"), "node_type")
        # EKS Node Instance Quantity
        self.context["eks_node_quantity"] = int(self.handle_property(app.node.try_get_context("node_quantity"),
                                                                     "node_quantity"))
        # EKS Node Boot Volume Size (in GB)
        self.context["eks_node_disk_size"] = int(self.handle_property(app.node.try_get_context("node_disk_size"),
                                                                      "node_disk_size"))
        # EKS Node Version (e.g. 1.19.6-20210414)
        # You can look this up here https://docs.aws.amazon.com/eks/latest/userguide/eks-linux-ami-versions.html
        message = "https://docs.aws.amazon.com/eks/latest/userguide/eks-linux-ami-versions.html"
        self.context["eks_node_ami_version"] = self.handle_property(app.node.try_get_context("node_ami_version"),
                                                                    "node_ami_version", message=message)

        self.context["deploy_bastion"] = self.handle_property_default(app.node.try_get_context("deploy_bastion"),
                                                                      "deploy_bastion", True)
        if self.context["deploy_bastion"]:
            self.context["basiton_node_type"] = self.handle_property(
                app.node.try_get_context("basiton_node_type"),
                "basiton_node_type", required=True)
            self.context["basiton_disk_size"] = int(self.handle_property(app.node.try_get_context("basiton_disk_size"),
                                                                          "basiton_disk_size", required = True))

        # Deploy Client VPN?
        # Before setting this to true you'll need to create and upload your certs as per these instructions
        # And then put the ARNs below in client_certificate_arn and server_certificate_arn
        # https://docs.aws.amazon.com/vpn/latest/clientvpn-admin/client-authentication.html#mutual
        self.context["deploy_client_vpn"] = self.handle_property_default(app.node.try_get_context(
            "deploy_client_vpn"), "deploy_client_vpn", False)
        if self.context["deploy_client_vpn"]:
            self.context["client_certificate_arn"] = self.handle_property(
                app.node.try_get_context("client_certificate_arn"), "client_certificate_arn")
            self.context["server_certificate_arn"] = self.handle_property(
                app.node.try_get_context("server_certificate_arn"), "server_certificate_arn")
            # CIDR Block for VPN Clients (has to be at least a /22)
            self.context["vpn_client_cidr_block"] = self.handle_property(app.node.try_get_context(
                "vpn_client_cidr_block"), "vpn_client_cidr_block")

        # Create a new VPC for the cluster?
        # If you set this to False then specify the VPC name to use below
        self.context["create_new_vpc"] = self.handle_property_default(app.node.try_get_context("create_new_vpc"),
                                                                      "create_new_vpc", True)
        # Set this to the CIDR for your new VPC
        self.context["vpc_cidr"] = self.handle_property(app.node.try_get_context("vpc_cidr"), "vpc_cidr")
        # Set this to the CIDR mask/size for your public subnets
        self.context["vpc_cidr_mask_public"] = int(
            self.handle_property(app.node.try_get_context("vpc_cidr_mask_public"),
                                 "vpc_cidr_mask_public"))
        # Set this to the CIDR mask/size for your private subnets
        self.context["vpc_cidr_mask_private"] = int(
            self.handle_property(app.node.try_get_context("vpc_cidr_mask_private"),
                                 "vpc_cidr_mask_private"))
        if not self.context["create_new_vpc"]:
            # If create_new_vpc is False then enter the name of the existing VPC to use
            # Note that if you use an existing VPC you'll need to tag the subnets as
            # described here https://aws.amazon.com/premiumsupport/knowledge-center/eks-vpc-subnet-discovery/
            message = "described here https://aws.amazon.com/premiumsupport/knowledge-center/eks-vpc-subnet-discovery/"
            self.context["existing_vpc_name"] = self.handle_property(app.node.try_get_context("existing_vpc_name"),
                                                                     "existing_vpc_name", message)
        # Create a new role as the initial admin for the cluster?
        self.context["create_new_cluster_admin_role"] = self.handle_property_default(
            app.node.try_get_context("create_new_cluster_admin_role"),
            "create_new_cluster_admin_role", True)
        # If create_new_cluster_admin_role is False then provide the ARN of the existing role to use
        if not self.context["create_new_cluster_admin_role"]:
            self.context.existing_role_arn = self.handle_property(app.node.try_get_context("existing_role_arn"),
                                                                  "existing_role_arn")
        # Deploy the AWS Load Balancer Controller?
        self.context["deploy_aws_lb_controller"] = self.handle_property_default(
            app.node.try_get_context("deploy_aws_lb_controller"),
            "deploy_aws_lb_controller", True)
        # Deploy ExternalDNS?
        self.context["deploy_external_dns"] = self.handle_property_default(
            app.node.try_get_context("deploy_external_dns"),
            "deploy_external_dns", True)

        # Deploy managed Elasticsearch and fluent-bit Daemonset?
        self.context["deploy_managed_elasticsearch"] = self.handle_property_default(
            app.node.try_get_context("deploy_managed_elasticsearch"),
            "deploy_managed_elasticsearch", True)
        # The capacity in Nodes and
        if self.context["deploy_managed_elasticsearch"]:
            self.context["es_capacity"] = es.CapacityConfig(
                data_nodes=int(self.handle_property(app.node.try_get_context("es_data_nodes"), "es_data_nodes")),
                data_node_instance_type=self.handle_property(app.node.try_get_context("es_data_node_instance_type"),
                                                             "es_data_node_instance_type"),
                master_nodes=int(self.handle_property(app.node.try_get_context("es_master_nodes"), "es_master_nodes")),
                master_node_instance_type=self.handle_property(app.node.try_get_context("es_master_node_instance_type"),
                                                               "es_master_node_instance_type")
            )
            # Volume Size/Type for the AWS Elasticsearch
            self.context["es_ebs"] = es.EbsOptions(
                enabled=self.handle_property_default(app.node.try_get_context("es_enabled"),
                                                     "es_enabled", True),
                volume_type=self.set_ec2_ebs(app.node.try_get_context("es_volume_type")),
                volume_size=int(self.handle_property(app.node.try_get_context("es_volume_size"),
                                                     "es_volume_size"))
            )
        # Deploy the kube-prometheus operator (on-cluster Prometheus & Grafana)?
        self.context["deploy_kube_prometheus_operator"] = self.handle_property_default(
            app.node.try_get_context("deploy_kube_prometheus_operator"),
            "deploy_kube_prometheus_operator", True)
        # Deploy AWS EBS CSI Driver?
        self.context["deploy_aws_ebs_csi"] = self.handle_property_default(
            app.node.try_get_context("deploy_aws_ebs_csi"),
            "deploy_aws_ebs_csi", True)
        # Deploy AWS EFS CSI Driver?
        self.context["deploy_aws_efs_csi"] = self.handle_property_default(
            app.node.try_get_context("deploy_aws_efs_csi"),
            "deploy_aws_efs_csi", True)

        # Deploy OPA Gatekeeper?
        self.context["deploy_opa_gatekeeper"] = self.handle_property_default(
            app.node.try_get_context("deploy_opa_gatekeeper"),
            "deploy_opa_gatekeeper", True)
        if self.context["deploy_opa_gatekeeper"]:
            # Deploy example Gatekeeper policies?
            self.context["deploy_gatekeeper_policies"] = self.handle_property_default(
                app.node.try_get_context("deploy_gatekeeper_policies"),
                "deploy_gatekeeper_policies", True)
            # Gateekeper policies git repo
            self.context["gatekeeper_policies_git_url"] = self.handle_property(
                app.node.try_get_context("gatekeeper_policies_git_url"),
                "gatekeeper_policies_git_url")
            # Gatekeeper policies git branch
            self.context["gatekeeper_policies_git_branch"] = self.handle_property(
                app.node.try_get_context("gatekeeper_policies_git_branch"),
                "gatekeeper_policies_git_branch")

            # Gatekeeper policies git path
            self.context["gatekeeper_policies_git_path"] = self.handle_property(
                app.node.try_get_context("gatekeeper_policies_git_path"),
                "gatekeeper_policies_git_path")
        # Deploy Cluster Autoscaler
        self.context["deploy_cluster_autoscaler"] = self.handle_property_default(
            app.node.try_get_context("deploy_cluster_autoscaler"),
            "deploy_cluster_autoscaler", True)

        # Deploy metrics-server (required for the Horizontal Pod Autoscaler (HPA))?
        self.context["deploy_metrics_server"] = self.handle_property_default(
            app.node.try_get_context("deploy_metrics_server"),
            "deploy_metrics_server", True)

        # Deploy Calico Network Policy Provider
        self.context["deploy_calico_np"] = self.handle_property_default(app.node.try_get_context("deploy_calico_np"),
                                                                        "deploy_calico_np", True)

        # Deploy AWS Simple Systems Manager (SSM) Agent?
        self.context["deploy_ssm_agent"] = self.handle_property_default(app.node.try_get_context("deploy_ssm_agent"),
                                                                        "deploy_ssm_agent", True)

    @property
    def outputs(self):
        return self.context
