The operator is hanging on the VPC discovery call (describe_cluster or describe_vpcs) -- it gets to "VPC Endpoint check starting" but never proceeds. The EC2 API is unreachable from the operator pod (no VPC endpoint for EC2 exists).

This is the fundamental chicken-and-egg problem: the operator needs VPC endpoints to create VPC endpoints.

The solution is the admin must create the EC2 VPC endpoint first (via Console), so the operator can then create the rest. Or better -- the admin creates ALL the essential endpoints via Console since the operator can't reach any AWS service without them.

Tell the admin to create these endpoints via VPC Console:

VPC Console -> Endpoints -> Create endpoint (repeat for each):

Service	Type	Attach To
com.amazonaws.ap-southeast-1.ec2	Interface	EKS subnets + SG allowing 443
com.amazonaws.ap-southeast-1.s3	Gateway	ALL route tables (including EKS node route tables)
com.amazonaws.ap-southeast-1.dynamodb	Gateway	ALL route tables
com.amazonaws.ap-southeast-1.sts	Interface	EKS subnets
com.amazonaws.ap-southeast-1.ssm	Interface	EKS subnets
com.amazonaws.ap-southeast-1.secretsmanager	Interface	EKS subnets
com.amazonaws.ap-southeast-1.glue	Interface	EKS subnets
com.amazonaws.ap-southeast-1.cognito-idp	Interface	EKS subnets
com.amazonaws.ap-southeast-1.logs	Interface	EKS subnets
For Interface endpoints: enable Private DNS, use a security group that allows inbound TCP 443 from the VPC CIDR.

Meanwhile, fix the operator crash -- delete the TotogiNetworkConfig so the operator stops trying to provision endpoints:

kubectl delete tnc vpc-endpoints 2>/dev/null || \
  kubectl patch tnc vpc-endpoints --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null
kubectl delete pod -n totogi-system --all