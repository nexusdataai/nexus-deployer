#!/usr/bin/env python3
"""
AWS Amplify UI Deployment Stack - Architecture Diagram
This script generates a comprehensive architecture diagram for the AWS Amplify UI deployment stack
using the diagrams library.
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import *
from diagrams.aws.database import *
from diagrams.aws.network import *
from diagrams.aws.storage import *
from diagrams.aws.analytics import *
from diagrams.aws.integration import *
from diagrams.aws.security import *
from diagrams.aws.devtools import *
from diagrams.aws.management import *
from diagrams.aws.mobile import *
from diagrams.aws.general import *

def create_ui_deployment_architecture():
    """
    Creates the main UI deployment architecture diagram
    """
    
    with Diagram(
        "DEPLOYMENT ARCHITECTURE",
        show=False,
        direction="TB",
        filename="ui_deployment_architecture",
        graph_attr={
            "fontsize": "32",
            "labelfontsize": "32",
            "labelfontname": "Arial Bold",
            "bgcolor": "white",
            "pad": "0.5",
            "rankdir": "TB",
            "splines": "ortho",
            "nodesep": "0.6",
            "ranksep": "1.0",
            "concentrate": "true",
            "compound": "true"
        }
    ):
        
        # Users & External
        with Cluster("Users & External"):
            user = User("End Users")
            github = General("GitHub\nRepository")
            adfs = General("ADFS\nDirectory")
        
        # DNS & Security
        with Cluster("DNS & Security"):
            route53 = Route53("Route 53\nDNS")
            acm = CertificateManager("ACM\nSSL Cert")
            waf = WAF("AWS WAF\nFirewall")
            shield = Shield("Shield\nDDoS")
        
        # CDN & Distribution
        with Cluster("CDN & Edge"):
            cloudfront = CloudFront("CloudFront\nCDN")
            edge_sg = CloudFrontEdgeLocation("Singapore")
            edge_tokyo = CloudFrontEdgeLocation("Tokyo")
            edge_sydney = CloudFrontEdgeLocation("Sydney")
        
        # Authentication
        with Cluster("Authentication"):
            cognito = Cognito("Cognito\nUser Pool")
            secrets_manager = SecretsManager("Secrets\nManager")
        
        # Application Layer
        with Cluster("Application - ap-southeast-1"):
            amplify = Amplify("Amplify\nHosting")
            s3_hosting = S3("S3\nAssets")
        
        # CI/CD & Monitoring
        with Cluster("CI/CD & Monitoring"):
            codecommit = Codecommit("CodeCommit")
            codebuild = Codebuild("CodeBuild")
            codedeploy = Codedeploy("CodeDeploy")
            cloudwatch = Cloudwatch("CloudWatch")
            xray = XRay("X-Ray")
            logs_bucket = S3("Logs\nBucket")
        
        # Flows
        user >> route53 >> cloudfront >> amplify
        github >> codecommit >> codebuild >> amplify
        user >> cognito >> amplify
        adfs >> cognito
        cloudfront >> waf >> shield
        acm >> cloudfront
        amplify >> s3_hosting
        amplify >> secrets_manager
        codebuild >> secrets_manager
        codedeploy >> amplify
        [amplify, cloudfront, cognito] >> cloudwatch
        amplify >> xray
        cloudfront >> logs_bucket
        cloudfront >> [edge_sg, edge_tokyo, edge_sydney]

def create_ui_security_architecture():
    """
    Creates the security architecture diagram
    """
    
    with Diagram(
        "SECURITY ARCHITECTURE",
        show=False,
        direction="LR",
        filename="ui_security_architecture",
        graph_attr={
            "fontsize": "32",
            "labelfontsize": "32",
            "labelfontname": "Arial Bold",
            "bgcolor": "white",
            "pad": "0.5",
            "rankdir": "LR",
            "splines": "ortho",
            "nodesep": "0.8",
            "ranksep": "1.2"
        }
    ):
        
        internet = General("Internet\n(Potential Threats)")
        
        with Cluster("Layer 1: DNS Security"):
            route53_security = Route53("Route 53\n• DNS Security Extensions\n• Health Checks\n• Failover Routing")
        
        with Cluster("Layer 2: Edge Security"):
            shield_advanced = Shield("AWS Shield\n• DDoS Protection\n• Attack Mitigation\n• 24/7 Response Team")
            waf_detailed = WAF("AWS WAF\n• OWASP Top 10 Protection\n• Rate Limiting\n• Geo Blocking\n• Custom Rules")
        
        with Cluster("Layer 3: Transport Security"):
            acm_security = CertificateManager("ACM Certificate\n• TLS 1.2+ Only\n• Perfect Forward Secrecy\n• Auto-renewal")
            cloudfront_security = CloudFront("CloudFront Security\n• HTTPS Redirect\n• Security Headers\n• Origin Access Identity")
        
        with Cluster("Layer 4: Application Security"):
            amplify_security = Amplify("Amplify Security\n• IAM Integration\n• Environment Variables\n• Build Security")
            s3_security = S3("S3 Security\n• Bucket Policies\n• Encryption at Rest\n• Access Logging")
        
        with Cluster("Layer 5: Monitoring & Compliance"):
            cloudwatch_security = Cloudwatch("Security Monitoring\n• Real-time Alerts\n• Log Analysis\n• Compliance Reports")
            cloudtrail = Cloudtrail("CloudTrail\n• API Logging\n• Audit Trail\n• Compliance")
        
        internet >> route53_security
        route53_security >> shield_advanced
        shield_advanced >> waf_detailed
        waf_detailed >> acm_security
        acm_security >> cloudfront_security
        cloudfront_security >> amplify_security
        amplify_security >> s3_security
        
        [waf_detailed, cloudfront_security, amplify_security, s3_security] >> cloudwatch_security
        [route53_security, waf_detailed, cloudfront_security, amplify_security] >> cloudtrail

def create_ui_authentication_architecture():
    """
    Creates the authentication architecture diagram
    """
    
    with Diagram(
        "AUTHENTICATION ARCHITECTURE",
        show=False,
        direction="LR",
        filename="ui_authentication_architecture",
        graph_attr={
            "fontsize": "32",
            "labelfontsize": "32",
            "labelfontname": "Arial Bold",
            "bgcolor": "white",
            "pad": "0.5",
            "rankdir": "LR",
            "splines": "ortho",
            "nodesep": "0.8",
            "ranksep": "1.2"
        }
    ):
        
        with Cluster("Users & Identity Sources"):
            end_users = Users("End Users\n(Web/Mobile)")
            corporate_users = General("Corporate Users\n(ADFS Domain)")
            adfs_server = General("ADFS Server\nActive Directory\nFederation Services")
        
        with Cluster("Authentication Services - ap-southeast-1"):
            cognito_user_pool = Cognito("Cognito User Pool\n• User Management\n• SAML/OIDC Provider\n• Multi-factor Auth\n• Custom Attributes")
            cognito_identity_pool = Cognito("Cognito Identity Pool\n• Federated Identities\n• Temporary AWS Credentials\n• Role-based Access")
        
        with Cluster("Secret Management - ap-southeast-1"):
            secrets_manager = SecretsManager("AWS Secrets Manager\n• OAuth Client Secrets\n• API Keys\n• Database Credentials\n• Auto Rotation")
            parameter_store = SystemsManagerParameterStore("Parameter Store\n• Configuration Values\n• Environment Variables\n• Secure Strings")
        
        with Cluster("Application Layer"):
            amplify_auth = Amplify("Amplify App\n• Cognito Integration\n• Protected Routes\n• JWT Validation")
            api_gateway = APIGateway("API Gateway\n• Cognito Authorizer\n• JWT Validation\n• Rate Limiting")
            lambda_function = Lambda("Lambda Functions\n• Business Logic\n• Secret Retrieval\n• Token Validation")
        
        with Cluster("Monitoring & Audit"):
            cloudwatch_auth = Cloudwatch("CloudWatch\n• Auth Metrics\n• Failed Login Alerts\n• Usage Analytics")
            cloudtrail_auth = Cloudtrail("CloudTrail\n• API Audit Logs\n• Secret Access Logs\n• Compliance Reports")
        
        end_users >> Edge(label="Direct Login", color="blue") >> cognito_user_pool
        corporate_users >> Edge(label="SSO Request", color="green") >> adfs_server
        adfs_server >> Edge(label="SAML Response", color="green") >> cognito_user_pool
        
        cognito_user_pool >> Edge(label="JWT Token", color="purple") >> cognito_identity_pool
        cognito_identity_pool >> Edge(label="AWS Credentials", color="purple") >> amplify_auth
        
        amplify_auth >> Edge(label="Protected Routes", color="orange") >> api_gateway
        api_gateway >> Edge(label="Authorized Requests", color="orange") >> lambda_function
        
        lambda_function >> Edge(label="Retrieve Secrets", color="red") >> secrets_manager
        amplify_auth >> Edge(label="Config Values", color="red") >> parameter_store
        
        [cognito_user_pool, cognito_identity_pool, amplify_auth, api_gateway] >> cloudwatch_auth
        [cognito_user_pool, secrets_manager, parameter_store] >> cloudtrail_auth

def create_ui_performance_architecture():
    """
    Creates the performance architecture diagram
    """
    
    with Diagram(
        "PERFORMANCE ARCHITECTURE",
        show=False,
        direction="TB",
        filename="ui_performance_architecture",
        graph_attr={
            "fontsize": "32",
            "labelfontsize": "32",
            "labelfontname": "Arial Bold",
            "bgcolor": "white",
            "pad": "0.5",
            "rankdir": "TB",
            "splines": "ortho",
            "nodesep": "0.6",
            "ranksep": "1.0"
        }
    ):
        
        with Cluster("Performance Monitoring"):
            cloudwatch_perf = Cloudwatch("CloudWatch\n• Performance Metrics\n• Custom Dashboards\n• Alarms")
            xray_perf = XRay("X-Ray\n• Distributed Tracing\n• Service Map\n• Performance Insights")
        
        with Cluster("CDN Performance"):
            cloudfront_perf = CloudFront("CloudFront\n• Global Edge Locations\n• Caching Strategies\n• Compression")
            edge_locations = CloudFrontEdgeLocation("Edge Locations\n• 400+ Locations\n• Low Latency\n• High Throughput")
        
        with Cluster("Application Performance"):
            amplify_perf = Amplify("Amplify\n• Build Optimization\n• Asset Minification\n• Tree Shaking")
            s3_perf = S3("S3\n• Transfer Acceleration\n• Multi-part Upload\n• Intelligent Tiering")
        
        with Cluster("Database Performance"):
            dynamodb_perf = DynamodbTable("DynamoDB\n• Auto Scaling\n• DAX Caching\n• Global Tables")
            elasticache = ElastiCache("ElastiCache\n• Redis/Memcached\n• Sub-millisecond\n• High Throughput")
        
        cloudwatch_perf >> [cloudfront_perf, amplify_perf, dynamodb_perf]
        xray_perf >> [amplify_perf, dynamodb_perf]
        cloudfront_perf >> edge_locations
        amplify_perf >> s3_perf
        dynamodb_perf >> elasticache

if __name__ == "__main__":
    print("Generating AWS Amplify UI architecture diagrams...")
    
    create_ui_deployment_architecture()
    print("✓ UI deployment architecture diagram created")
    
    create_ui_security_architecture()
    print("✓ UI security architecture diagram created")
    
    create_ui_authentication_architecture()
    print("✓ UI authentication architecture diagram created")
    
    create_ui_performance_architecture()
    print("✓ UI performance architecture diagram created")
    
    print("\nAll diagrams generated successfully!")
    print("Files created:")
    print("- ui_deployment_architecture.png")
    print("- ui_security_architecture.png")
    print("- ui_authentication_architecture.png")
    print("- ui_performance_architecture.png")