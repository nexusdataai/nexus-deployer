"""
Certificate Validation Service
Validates ACM certificate requirements before deployment
"""
import boto3
from typing import Dict, Optional, Tuple
from botocore.exceptions import ClientError


class CertificateValidator:
    """Validates ACM certificate requirements"""
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize certificate validator
        
        Args:
            credentials: Optional AWS credentials dict
        """
        self.credentials = credentials or {}
    
    def _get_client(self, service: str, region: str):
        """Get boto3 client with credentials"""
        return boto3.client(service, region_name=region, **self.credentials)
    
    def validate_hosted_zone(self, hosted_zone_id: str, base_domain: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that the hosted zone exists and matches the domain
        
        Args:
            hosted_zone_id: Route53 hosted zone ID
            base_domain: Base domain name
            
        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        try:
            route53 = self._get_client('route53', 'us-east-1')
            
            # Get hosted zone details
            response = route53.get_hosted_zone(Id=hosted_zone_id)
            hosted_zone = response.get('HostedZone', {})
            
            # Get the domain name from the hosted zone (remove trailing dot)
            hz_domain = hosted_zone.get('Name', '').rstrip('.')
            
            # Check if domains match
            if hz_domain.lower() != base_domain.lower():
                return False, f"Hosted zone domain '{hz_domain}' does not match base domain '{base_domain}'"
            
            return True, None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchHostedZone':
                return False, f"Hosted zone '{hosted_zone_id}' does not exist"
            return False, f"Error validating hosted zone: {str(e)}"
        except Exception as e:
            return False, f"Error validating hosted zone: {str(e)}"
    
    def check_route53_permissions(self) -> Tuple[bool, Optional[str]]:
        """
        Check if we have necessary Route53 permissions
        
        Returns:
            Tuple of (has_permissions: bool, error_message: Optional[str])
        """
        try:
            route53 = self._get_client('route53', 'us-east-1')
            
            # Try to list hosted zones
            route53.list_hosted_zones(MaxItems='1')
            
            return True, None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            return False, f"Missing Route53 permissions: {error_code}"
        except Exception as e:
            return False, f"Error checking Route53 permissions: {str(e)}"
    
    def check_acm_permissions(self, region: str = 'us-east-1') -> Tuple[bool, Optional[str]]:
        """
        Check if we have necessary ACM permissions
        
        Args:
            region: AWS region (default: us-east-1 for CloudFront certificates)
            
        Returns:
            Tuple of (has_permissions: bool, error_message: Optional[str])
        """
        try:
            acm = self._get_client('acm', region)
            
            # Try to list certificates
            acm.list_certificates(MaxItems=1)
            
            return True, None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            return False, f"Missing ACM permissions: {error_code}"
        except Exception as e:
            return False, f"Error checking ACM permissions: {str(e)}"
    
    def check_existing_certificate(self, domain_name: str, region: str = 'us-east-1') -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if a certificate already exists for the domain
        
        Args:
            domain_name: Domain name to check
            region: AWS region
            
        Returns:
            Tuple of (exists: bool, certificate_arn: Optional[str], status: Optional[str])
        """
        try:
            acm = self._get_client('acm', region)
            
            # List all certificates
            response = acm.list_certificates()
            certificates = response.get('CertificateSummaryList', [])
            
            # Check for matching domain
            for cert in certificates:
                if cert.get('DomainName') == domain_name:
                    cert_arn = cert.get('CertificateArn')
                    
                    # Get certificate details
                    cert_details = acm.describe_certificate(CertificateArn=cert_arn)
                    cert_info = cert_details.get('Certificate', {})
                    status = cert_info.get('Status')
                    
                    return True, cert_arn, status
            
            return False, None, None
            
        except Exception as e:
            return False, None, f"Error: {str(e)}"
    
    def validate_certificate_requirements(self, config: Dict) -> Tuple[bool, list]:
        """
        Validate all certificate requirements before deployment
        
        Args:
            config: Deployment configuration
            
        Returns:
            Tuple of (is_valid: bool, errors: list)
        """
        errors = []
        
        # Get configuration values
        domain_config = config.get('infrastructure', {}).get('domain', {})
        base_domain = domain_config.get('base', '')
        hosted_zone_id = domain_config.get('hosted_zone_id', '')
        frontend_subdomain = domain_config.get('frontend_subdomain', 'app')
        
        # Validate base domain
        if not base_domain:
            errors.append("Base domain is not configured")
        
        # Validate hosted zone ID
        if not hosted_zone_id:
            errors.append("Hosted zone ID is not configured")
        
        # If we have both, validate they match
        if base_domain and hosted_zone_id:
            is_valid, error = self.validate_hosted_zone(hosted_zone_id, base_domain)
            if not is_valid:
                errors.append(error)
        
        # Check Route53 permissions
        has_perms, error = self.check_route53_permissions()
        if not has_perms:
            errors.append(error)
        
        # Check ACM permissions
        has_perms, error = self.check_acm_permissions()
        if not has_perms:
            errors.append(error)
        
        # Check for existing certificate
        if base_domain and frontend_subdomain:
            full_domain = f"{frontend_subdomain}.{base_domain}"
            exists, cert_arn, status = self.check_existing_certificate(full_domain)
            
            if exists:
                if status == 'PENDING_VALIDATION':
                    errors.append(f"Certificate for {full_domain} exists but is PENDING_VALIDATION. "
                                f"Please complete DNS validation or delete the certificate.")
                elif status == 'FAILED':
                    errors.append(f"Certificate for {full_domain} exists but is in FAILED state. "
                                f"Please delete the certificate before deploying.")
        
        return len(errors) == 0, errors
