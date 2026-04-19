/**
 * Welcome Screen Component
 * Simplified hero-style landing page for Totogi Capability Installer
 */
import React, { useState } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import InstallationHistory from './InstallationHistory';

// Hero SVG illustration for Telco Business Capability deployment
const HeroIllustration: React.FC = () => (
  <svg
    viewBox="0 0 400 280"
    className="w-full max-w-md mx-auto"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    {/* Telco Business Capability Box at top */}
    <rect x="140" y="10" width="120" height="50" rx="8" fill="#6366F1" stroke="#4F46E5" strokeWidth="2" />
    <text x="200" y="30" textAnchor="middle" fill="white" fontSize="10" fontWeight="600">
      Telco Business
    </text>
    <text x="200" y="45" textAnchor="middle" fill="white" fontSize="10" fontWeight="600">
      Capability
    </text>
    
    {/* Signal/telecom icon inside capability box */}
    <circle cx="160" cy="35" r="8" fill="none" stroke="#A5B4FC" strokeWidth="1.5" />
    <circle cx="160" cy="35" r="4" fill="#A5B4FC" />
    
    {/* Download arrow from capability to cloud */}
    <path
      d="M200 65 L200 95"
      stroke="#1D4ED8"
      strokeWidth="3"
      strokeLinecap="round"
    />
    <path
      d="M190 85 L200 98 L210 85"
      stroke="#1D4ED8"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    
    {/* Cloud background */}
    <ellipse cx="200" cy="150" rx="130" ry="70" fill="#E0F2FE" />
    <ellipse cx="130" cy="165" rx="50" ry="35" fill="#E0F2FE" />
    <ellipse cx="270" cy="165" rx="50" ry="35" fill="#E0F2FE" />
    
    {/* Main cloud shape */}
    <path
      d="M90 170 C90 135, 125 115, 160 115 C175 85, 225 85, 240 115 C275 115, 310 135, 310 170 C310 205, 275 220, 240 220 L160 220 C125 220, 90 205, 90 170Z"
      fill="#BFDBFE"
      stroke="#3B82F6"
      strokeWidth="2"
    />
    
    {/* Server/capability module 1 - green */}
    <rect x="125" y="140" width="45" height="55" rx="4" fill="#10B981" stroke="#059669" strokeWidth="2" />
    <rect x="132" y="148" width="31" height="5" rx="2" fill="#D1FAE5" />
    <rect x="132" y="158" width="31" height="5" rx="2" fill="#D1FAE5" />
    <rect x="132" y="168" width="31" height="5" rx="2" fill="#D1FAE5" />
    <circle cx="139" cy="183" r="3" fill="#34D399" />
    
    {/* Server/capability module 2 - blue */}
    <rect x="230" y="140" width="45" height="55" rx="4" fill="#3B82F6" stroke="#2563EB" strokeWidth="2" />
    <rect x="237" y="148" width="31" height="5" rx="2" fill="#DBEAFE" />
    <rect x="237" y="158" width="31" height="5" rx="2" fill="#DBEAFE" />
    <rect x="237" y="168" width="31" height="5" rx="2" fill="#DBEAFE" />
    <circle cx="244" cy="183" r="3" fill="#60A5FA" />
    
    {/* Connection lines to infrastructure */}
    <path
      d="M147 205 L147 235 M253 205 L253 235"
      stroke="#94A3B8"
      strokeWidth="2"
      strokeDasharray="4 4"
    />
    
    {/* Infrastructure base - Your Environment */}
    <rect x="100" y="240" width="200" height="30" rx="4" fill="#F1F5F9" stroke="#CBD5E1" strokeWidth="2" />
    <text x="200" y="260" textAnchor="middle" fill="#64748B" fontSize="11" fontWeight="500">
      Your Environment
    </text>
    
    {/* Success checkmark badge */}
    <circle cx="300" cy="120" r="18" fill="#10B981" />
    <path
      d="M291 120 L297 126 L309 114"
      stroke="white"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

// AWS Icon SVG - Official AWS Logo Style (grey background, black text, orange smile)
const AwsIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg viewBox="0 0 40 40" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Light grey background */}
    <rect width="40" height="40" rx="8" fill="#F3F4F6" />
    {/* AWS Logo */}
    <g transform="translate(4, 8)">
      {/* "aws" text in black */}
      <text x="16" y="16" textAnchor="middle" fill="#232F3E" fontSize="12" fontWeight="700" fontFamily="Arial, sans-serif">
        aws
      </text>
      {/* Orange smile/arrow */}
      <path 
        d="M6 22 Q16 26 26 22" 
        stroke="#FF9900" 
        strokeWidth="2.5" 
        strokeLinecap="round"
        fill="none"
      />
      {/* Arrow tip */}
      <path 
        d="M24 20 L27 22 L24 24" 
        stroke="#FF9900" 
        strokeWidth="2" 
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </g>
  </svg>
);

// Azure Icon SVG
const AzureIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg viewBox="0 0 40 40" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="40" height="40" rx="8" fill="#0078D4" />
    <path d="M12 28l6-16h4l-8 16h-2z" fill="white" fillOpacity="0.8"/>
    <path d="M16 12l10 14H14l2-4h6l-6-10z" fill="white"/>
  </svg>
);

// GCP Icon SVG
const GcpIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg viewBox="0 0 40 40" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="40" height="40" rx="8" fill="#4285F4" />
    <path d="M20 10l8 5v10l-8 5-8-5V15l8-5z" fill="white" fillOpacity="0.3"/>
    <path d="M20 12l6 3.75v7.5L20 27l-6-3.75v-7.5L20 12z" fill="none" stroke="white" strokeWidth="2"/>
    <circle cx="20" cy="20" r="4" fill="white"/>
  </svg>
);

// Kubernetes Icon SVG
const KubernetesIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg viewBox="0 0 40 40" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="40" height="40" rx="8" fill="#326CE5" />
    <path d="M20 8l10 6v12l-10 6-10-6V14l10-6z" fill="white" fillOpacity="0.2"/>
    <circle cx="20" cy="20" r="6" fill="none" stroke="white" strokeWidth="2"/>
    <circle cx="20" cy="20" r="2" fill="white"/>
    <path d="M20 14v-2M20 28v-2M14 20h-2M28 20h-2M15.5 15.5l-1.5-1.5M26 26l-1.5-1.5M15.5 24.5l-1.5 1.5M26 14l-1.5 1.5" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
  </svg>
);

// On-Premise/Server Icon SVG
const OnPremiseIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg viewBox="0 0 40 40" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="40" height="40" rx="8" fill="#6B7280" />
    <rect x="10" y="8" width="20" height="8" rx="2" fill="white"/>
    <circle cx="14" cy="12" r="1.5" fill="#6B7280"/>
    <rect x="18" y="11" width="8" height="2" rx="1" fill="#6B7280"/>
    <rect x="10" y="18" width="20" height="8" rx="2" fill="white"/>
    <circle cx="14" cy="22" r="1.5" fill="#6B7280"/>
    <rect x="18" y="21" width="8" height="2" rx="1" fill="#6B7280"/>
    <rect x="10" y="28" width="20" height="8" rx="2" fill="white" fillOpacity="0.7"/>
    <circle cx="14" cy="32" r="1.5" fill="#6B7280"/>
    <rect x="18" y="31" width="8" height="2" rx="1" fill="#6B7280"/>
  </svg>
);

// Checkmark Icon for supported platforms
const CheckmarkIcon: React.FC = () => (
  <svg viewBox="0 0 16 16" className="w-4 h-4" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="8" cy="8" r="8" fill="#10B981" />
    <path d="M5 8l2 2 4-4" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// Platform support configuration interface
interface DeploymentPlatform {
  id: string;
  name: string;
  icon: React.ReactNode;
  isSupported: boolean;
  tooltipText: string;
}

// Deployment platforms configuration
const DEPLOYMENT_PLATFORMS: DeploymentPlatform[] = [
  { id: 'aws', name: 'AWS', icon: <AwsIcon className="w-10 h-10" />, isSupported: true, tooltipText: 'Supported' },
  { id: 'azure', name: 'Azure', icon: <AzureIcon className="w-10 h-10" />, isSupported: false, tooltipText: 'Coming Soon' },
  { id: 'gcp', name: 'GCP', icon: <GcpIcon className="w-10 h-10" />, isSupported: false, tooltipText: 'Coming Soon' },
  { id: 'kubernetes', name: 'Kubernetes', icon: <KubernetesIcon className="w-10 h-10" />, isSupported: false, tooltipText: 'Coming Soon' },
  { id: 'onpremise', name: 'On-Premise', icon: <OnPremiseIcon className="w-10 h-10" />, isSupported: false, tooltipText: 'Coming Soon' },
];

// PlatformIcon component with support indicator and tooltip
interface PlatformIconProps {
  platform: DeploymentPlatform;
}

const PlatformIcon: React.FC<PlatformIconProps> = ({ platform }) => {
  const [showTooltip, setShowTooltip] = React.useState(false);

  return (
    <div
      className="relative flex flex-col items-center"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      data-testid={`platform-icon-${platform.id}`}
    >
      {/* Platform icon with optional grayscale for unsupported */}
      <div className={`relative ${!platform.isSupported ? 'opacity-60 grayscale' : ''}`}>
        {platform.icon}
        {/* Checkmark overlay for supported platforms */}
        {platform.isSupported && (
          <div className="absolute -top-1 -right-1" data-testid={`checkmark-${platform.id}`}>
            <CheckmarkIcon />
          </div>
        )}
      </div>
      
      {/* Platform name */}
      <span className={`text-xs mt-1 ${platform.isSupported ? 'text-gray-700 font-medium' : 'text-gray-400'}`}>
        {platform.name}
      </span>
      
      {/* Tooltip */}
      {showTooltip && (
        <div 
          className="absolute -top-8 left-1/2 transform -translate-x-1/2 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap z-10"
          data-testid={`tooltip-${platform.id}`}
        >
          {platform.tooltipText}
          <div className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
        </div>
      )}
    </div>
  );
};

const WelcomeScreen: React.FC = () => {
  const { setStep } = useWizard();
  const [showHistory, setShowHistory] = useState(false);

  const handleStart = () => {
    setStep(WizardStep.CAPABILITY_SELECTION);
  };

  if (showHistory) {
    return (
      <div className="min-h-[600px] py-4">
        <InstallationHistory onClose={() => setShowHistory(false)} />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[600px]">
      <div className="max-w-2xl w-full bg-white rounded-lg shadow-lg p-12 text-center">
        {/* Hero Illustration */}
        <div className="mb-8">
          <HeroIllustration />
        </div>

        {/* Title */}
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          Totogi Capability Installer
        </h1>
        
        {/* Subtitle */}
        <p className="text-xl text-gray-600 mb-8">
          Deploy Business Capability in your Environment
        </p>

        {/* Platform Icons Row */}
        <div className="flex justify-center items-center gap-6 mb-10" data-testid="platform-icons-row">
          {DEPLOYMENT_PLATFORMS.map((platform) => (
            <PlatformIcon key={platform.id} platform={platform} />
          ))}
        </div>

        {/* Buttons */}
        <div className="flex flex-col gap-4 items-center">
          {/* Get Started Button */}
          <button
            onClick={handleStart}
            className="px-10 py-4 bg-blue-600 text-white text-lg font-semibold rounded-lg hover:bg-blue-700 transition-colors shadow-md hover:shadow-lg"
          >
            Get Started
          </button>
          
          {/* View Installation History Button */}
          <button
            onClick={() => setShowHistory(true)}
            className="px-6 py-2 text-gray-600 hover:text-gray-800 text-sm font-medium hover:underline"
          >
            View Installation History
          </button>
        </div>
      </div>
    </div>
  );
};

export default WelcomeScreen;
