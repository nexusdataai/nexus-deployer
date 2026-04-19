/**
 * AWS Service Icons as React components
 */
import React from 'react';

interface IconProps {
  className?: string;
}

export const CloudFrontIcon: React.FC<IconProps> = ({ className = 'w-8 h-8' }) => (
  <svg className={className} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M40 0C17.909 0 0 17.909 0 40s17.909 40 40 40 40-17.909 40-40S62.091 0 40 0z" fill="#8C4FFF"/>
    <path d="M40 16c-13.255 0-24 10.745-24 24s10.745 24 24 24 24-10.745 24-24-10.745-24-24-24zm0 42c-9.941 0-18-8.059-18-18s8.059-18 18-18 18 8.059 18 18-8.059 18-18 18z" fill="#fff"/>
    <circle cx="40" cy="40" r="8" fill="#fff"/>
  </svg>
);

export const S3Icon: React.FC<IconProps> = ({ className = 'w-8 h-8' }) => (
  <svg className={className} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M40 0L8 16v48l32 16 32-16V16L40 0z" fill="#569A31"/>
    <path d="M40 16L20 26v28l20 10 20-10V26L40 16z" fill="#fff" fillOpacity="0.3"/>
    <path d="M40 32v24M28 38l12 6 12-6" stroke="#fff" strokeWidth="3" strokeLinecap="round"/>
  </svg>
);

export const AmplifyIcon: React.FC<IconProps> = ({ className = 'w-8 h-8' }) => (
  <svg className={className} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M40 8L12 64h16l12-24 12 24h16L40 8z" fill="#FF9900"/>
    <path d="M40 24l-8 16h16l-8-16z" fill="#fff"/>
  </svg>
);

export const ECSIcon: React.FC<IconProps> = ({ className = 'w-8 h-8' }) => (
  <svg className={className} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="8" y="8" width="64" height="64" rx="8" fill="#ED7100"/>
    <rect x="16" y="20" width="20" height="16" rx="2" fill="#fff"/>
    <rect x="44" y="20" width="20" height="16" rx="2" fill="#fff"/>
    <rect x="16" y="44" width="20" height="16" rx="2" fill="#fff"/>
    <rect x="44" y="44" width="20" height="16" rx="2" fill="#fff"/>
  </svg>
);

export const EKSIcon: React.FC<IconProps> = ({ className = 'w-8 h-8' }) => (
  <svg className={className} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="8" y="8" width="64" height="64" rx="8" fill="#ED7100"/>
    <path d="M40 16l20 12v24L40 64 20 52V28l20-12z" fill="#fff" fillOpacity="0.3"/>
    <path d="M40 24l12 7.2v14.4L40 53l-12-7.2V31.2L40 24z" fill="#fff"/>
    <circle cx="40" cy="40" r="6" fill="#ED7100"/>
  </svg>
);

export const EC2Icon: React.FC<IconProps> = ({ className = 'w-8 h-8' }) => (
  <svg className={className} viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="8" y="8" width="64" height="64" rx="8" fill="#ED7100"/>
    <rect x="20" y="20" width="40" height="40" rx="4" fill="#fff"/>
    <rect x="28" y="28" width="24" height="24" rx="2" fill="#ED7100"/>
    <circle cx="40" cy="40" r="6" fill="#fff"/>
  </svg>
);

/**
 * Get icon component by service icon name
 */
export const getServiceIcon = (iconName: string): React.FC<IconProps> => {
  const icons: Record<string, React.FC<IconProps>> = {
    cloudfront: CloudFrontIcon,
    s3: S3Icon,
    amplify: AmplifyIcon,
    ecs: ECSIcon,
    eks: EKSIcon,
    ec2: EC2Icon,
  };
  return icons[iconName] || CloudFrontIcon;
};
