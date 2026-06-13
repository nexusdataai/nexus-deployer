# Nexus AI Customer Toolkit
## Enterprise-Grade Self-Service Cloud Deployment Platform

[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-AWS%20%7C%20Azure%20%7C%20GCP-orange.svg)](#supported-platforms)
[![Version](https://img.shields.io/badge/version-0.0.1-blue.svg)](doc/release-notes/)

> **📦 Kubernetes Operator:** All operator scripts are in [kube-operator/](kube-operator/) directory.
> Quick start: `cd kube-operator && ./build-and-deploy.sh` | [Scripts reference →](kube-operator/SCRIPTS.md)

---

## 🎯 What Is This?

The **Nexus AI Customer Toolkit** is an enterprise-grade deployment platform that enables customers to deploy complex, production-ready telecommunications and business capabilities to their own cloud infrastructure in **under 30 minutes** with **zero cloud expertise required**.

Think of it as **"Shopify for Enterprise Capabilities"** - a self-service platform that transforms months-long professional services engagements into simple, guided deployments.

### Key Value Propositions

- ⚡ **Deploy in 15-30 minutes** (vs. 3-6 months traditional)
- 💰 **Zero professional services costs** (vs. $100K-$500K per deployment)
- 🔐 **Complete customer control** - deploys into customer's own AWS account
- 🎓 **No cloud expertise required** - guided wizard handles all complexity
- 🌐 **Multi-cloud support** - AWS, Azure, GCP, Kubernetes, On-premise
- 📊 **Full lifecycle management** - deploy, update, monitor, and scale

---

## 📚 Documentation Hub

### For Business Stakeholders

| Document | Audience | Purpose |
|----------|----------|---------|
| [**Business Requirements**](doc/business/business-requirements.md) | Product, Sales, Customer Success | Complete business case, ROI, and customer value analysis |
| [**Executive Summary**](doc/business/executive-summary.md) | C-Level, Board, Investors | Strategic overview, financials, and market opportunity |
| [**Business Overview**](doc/business/README.md) | All Stakeholders | Quick reference guide with key metrics |

**Key Highlights:**
- 68% cost reduction for customers
- 94% faster time-to-value
- 191% first-year customer ROI
- 79% profit margins vs. 52% traditional

### For End Users

| Document | Audience | Purpose |
|----------|----------|---------|
| [**User Guide**](doc/user-guide/README.md) | All Users | Complete walkthrough of deployment process |
| [**Getting Started**](doc/user-guide/01-getting-started.md) | New Users | Prerequisites and quick start guide |
| [**Deployment Wizard**](doc/user-guide/03-deployment-wizard.md) | Operators | Step-by-step deployment instructions |
| [**AWS Configuration**](doc/user-guide/04-aws-configuration.md) | DevOps Engineers | AWS credential and permission setup |
| [**Managing Deployments**](doc/user-guide/05-managing-deployments.md) | Administrators | Update, monitor, and delete deployments |
| [**Troubleshooting**](doc/user-guide/06-troubleshooting.md) | Support Teams | Common issues and solutions |
| [**FAQ**](doc/user-guide/07-faq.md) | All Users | Frequently asked questions |

### For Technical Teams

| Document | Audience | Purpose |
|----------|----------|---------|
| [**Product Requirements**](doc/prd/requirement.md) | Product & Engineering | Detailed feature requirements and acceptance criteria |
| [**Solution Architecture**](doc/solution-architecture.md) | Architects & Engineers | Technical architecture and design decisions |
| [**Capability Architecture**](doc/capability-arcitechture/capability-arcitecture.md) | Cloud Architects | AWS infrastructure and service design |
| [**Deployment Code Flow**](docs/DEPLOYMENT_CODE_FLOW.md) | Developers | Backend deployment logic and code structure |
| [**Integration Test Guide**](backend/INTEGRATION_TEST_GUIDE.md) | QA Engineers | Testing strategies and test cases |

### For Developers

| Document | Audience | Purpose |
|----------|----------|---------|
| [**Startup Guide**](STARTUP_GUIDE.md) | Developers | How to run the application locally |
| [**Build Guide**](doc/user-guide/BUILD_GUIDE.md) | Build Engineers | Production build and packaging instructions |
| [**Wizard Reference**](WIZARD_COMPLETE_REFERENCE.md) | Frontend Developers | Complete wizard flow documentation |
| [**UI Integration Plan**](UI_INTEGRATION_PLAN.md) | Frontend Developers | Frontend architecture and integration |
| [**Deployment Strategy**](DEPLOYMENT_STRATEGY_GUIDE.md) | Backend Developers | Deployment logic and strategies |

---

## 🏗️ Architecture

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React + TypeScript + Vite + Tailwind CSS | Modern, responsive UI with type safety |
| **Backend** | Python + FastAPI + boto3 | High-performance API with AWS integration |
| **Desktop** | Electron | Cross-platform desktop application wrapper |
| **Packaging** | PyInstaller + electron-builder | Production build and distribution |
| **Infrastructure** | AWS CloudFormation | Infrastructure-as-Code deployments |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    End Users                                │
│          (Desktop App / PWA / Browser)                      │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │   Electron Desktop App          │
        │   - Windows, macOS, Linux       │
        │   - Offline capability          │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │   React Frontend (PWA)          │
        │   - Vite + TypeScript           │
        │   - Tailwind CSS                │
        │   - Service Workers             │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │   FastAPI Backend               │
        │   - Python 3.11+                │
        │   - boto3 AWS SDK               │
        │   - JWT Authentication          │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │   AWS CloudFormation            │
        │   - Template Generation         │
        │   - Stack Orchestration         │
        │   - Resource Provisioning       │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │   Customer AWS Account          │
        │   - VPC, ECS, RDS, S3, etc.     │
        │   - Complete infrastructure     │
        └─────────────────────────────────┘
```

For detailed architecture information, see:
- [Solution Architecture](doc/solution-architecture.md)
- [Capability Architecture](doc/capability-arcitechture/capability-arcitecture.md)

---

## 🚀 Quick Start

### For End Users

If you want to **use** the Nexus AI Customer Toolkit to deploy capabilities:

1. **Download** the installer for your platform (Windows, macOS, or Linux)
2. **Install** and launch the application
3. **Follow** the [User Guide](doc/user-guide/README.md)

See [Getting Started Guide](doc/user-guide/01-getting-started.md) for detailed instructions.

### For Developers

If you want to **develop** or **modify** the Nexus AI Customer Toolkit:

#### Prerequisites

- **Node.js** 18+ ([Download](https://nodejs.org/))
- **Python** 3.11+ ([Download](https://www.python.org/))
- **Git** ([Download](https://git-scm.com/))
- **AWS Account** (for testing deployments)

#### Automated Startup (Recommended)

**Windows:**
```bash
# Double-click or run:
start-app.bat
```

**Linux/Mac:**
```bash
# Make executable (first time only):
chmod +x start-app.sh

# Run:
./start-app.sh
```

This will automatically:
- ✅ Install all dependencies (first time only)
- ✅ Start backend on port 8001
- ✅ Start frontend on port 5173
- ✅ Launch Electron desktop app

See [STARTUP_GUIDE.md](STARTUP_GUIDE.md) for details.

#### Manual Setup (Alternative)

**Terminal 1 - Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Mac/Linux
# venv\Scripts\activate    # Windows
pip install -r requirements.txt
python app/main.py
# Backend runs on http://127.0.0.1:8001
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm install
npm run dev
# Frontend runs on http://localhost:5173
```

**Terminal 3 - Electron:**
```bash
cd electron
npm install
npm run dev
# Desktop app launches automatically
```

---

## 📁 Project Structure

```
nexus-deployer/
├── frontend/                 # React + TypeScript frontend
│   ├── src/
│   │   ├── components/      # Reusable UI components
│   │   ├── pages/           # Page components (wizard steps)
│   │   ├── services/        # API client services
│   │   └── types/           # TypeScript type definitions
│   ├── public/              # Static assets
│   └── package.json
│
├── backend/                  # Python FastAPI backend
│   ├── app/
│   │   ├── routers/         # API route handlers
│   │   ├── services/        # Business logic services
│   │   ├── models/          # Data models
│   │   ├── aws/             # AWS integration (boto3)
│   │   └── main.py          # Application entry point
│   ├── tests/               # Backend tests
│   └── requirements.txt
│
├── electron/                 # Electron desktop wrapper
│   ├── main.js              # Electron main process
│   ├── preload.js           # Preload script
│   └── package.json
│
├── deploy/                   # Deployment resources
│   ├── templates/           # CloudFormation templates
│   │   ├── frontend/        # Frontend infrastructure
│   │   └── backend/         # Backend infrastructure
│   ├── scripts/             # Deployment automation scripts
│   └── iam/                 # IAM policies and roles
│
├── doc/                      # Documentation
│   ├── business/            # Business requirements and ROI
│   ├── prd/                 # Product requirements
│   ├── user-guide/          # End user documentation
│   ├── capability-arcitechture/  # Technical architecture
│   └── release-notes/       # Version release notes
│
├── docs/                     # Additional technical docs
│   ├── DEPLOYMENT_CODE_FLOW.md
│   ├── UI_SCREENS_DETAILED.md
│   └── WIZARD_FLOW_SUMMARY.md
│
├── example/                  # Example deployments
│   ├── frontend/            # Frontend deployment examples
│   └── backend/             # Backend deployment examples
│
├── scripts/                  # Utility scripts
├── build/                    # Build output directory
├── start-app.bat            # Windows startup script
├── start-app.sh             # Linux/Mac startup script
├── stop-app.bat             # Windows stop script
├── stop-app.sh              # Linux/Mac stop script
└── README.md                # This file
```

---

## 🎯 Key Features

### For Customers

- **Self-Service Deployment**: Deploy capabilities without vendor professional services
- **Guided Wizard**: Step-by-step interface requiring no cloud expertise
- **Multi-Cloud Support**: AWS, Azure, GCP, Kubernetes, On-premise
- **Complete Control**: Deploys into customer's own cloud account
- **License Management**: Automatic entitlement validation and enforcement
- **Role-Based Access**: Administrator, Operator, and Viewer roles
- **Multi-Factor Authentication**: TOTP, SMS, and email-based MFA
- **Environment Management**: Separate dev, staging, and production deployments
- **Real-Time Monitoring**: Live deployment progress and health checks
- **Audit Trail**: Complete logging for compliance and security
- **Self-Service Updates**: Apply patches and updates without vendor involvement
- **Cost Transparency**: All cloud costs visible in customer's billing

### For Developers

- **Modern Tech Stack**: React, TypeScript, FastAPI, Python 3.11+
- **Type Safety**: Full TypeScript coverage on frontend
- **API Documentation**: Auto-generated OpenAPI/Swagger docs
- **Hot Reload**: Fast development with Vite and FastAPI auto-reload
- **Comprehensive Testing**: Unit tests, integration tests, E2E tests
- **Linting & Formatting**: ESLint, Prettier, Black, isort
- **CI/CD Ready**: GitHub Actions workflows included
- **Cross-Platform**: Build for Windows, macOS, and Linux
- **Extensible Architecture**: Plugin system for new capabilities
- **Well Documented**: Extensive inline documentation and guides

---

## 🔧 Development Workflow

### Running Tests

**Backend Tests:**
```bash
cd backend
pytest                      # Run all tests
pytest --cov=app           # With coverage report
pytest -v -s               # Verbose with output
pytest tests/test_api.py   # Specific test file
```

**Frontend Tests:**
```bash
cd frontend
npm test                   # Run all tests
npm run test:coverage      # With coverage report
npm run test:watch         # Watch mode
```

### Code Quality

**Backend:**
```bash
cd backend
black .                    # Format code
isort .                    # Sort imports
flake8                     # Lint code
mypy app                   # Type checking
```

**Frontend:**
```bash
cd frontend
npm run lint               # ESLint
npm run format             # Prettier
npm run type-check         # TypeScript checking
```

### Building for Production

See [BUILD_GUIDE.md](doc/user-guide/BUILD_GUIDE.md) for comprehensive build instructions.

**Quick Build:**
```bash
# 1. Build backend
cd backend
pyinstaller backend.spec

# 2. Build frontend
cd frontend
npm run build

# 3. Package desktop app
cd electron
npm run build:win          # Windows
npm run build:mac          # macOS
npm run build:linux        # Linux
```

**Build Outputs:**
- Windows: `dist/Nexus AI-Installer-Setup-{version}.exe`
- macOS: `dist/Nexus AI-Installer-{version}.dmg`
- Linux: `dist/Nexus AI-Installer-{version}.AppImage`

---

## 🛠️ Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **Backend won't start** | Check Python version (3.11+), activate venv, install requirements |
| **Frontend won't start** | Check Node version (18+), run `npm install`, clear node_modules |
| **Electron won't launch** | Ensure backend and frontend are running, check ports 8001/5173 |
| **Port already in use** | Change ports in config or stop conflicting processes |
| **AWS credentials invalid** | Verify credentials in AWS console, check IAM permissions |
| **Deployment fails** | Review CloudFormation errors, check AWS service quotas |

For detailed troubleshooting, see:
- [Troubleshooting Guide](doc/user-guide/06-troubleshooting.md)
- [FAQ](doc/user-guide/07-faq.md)

### Getting Help

- **Documentation**: Check the [User Guide](doc/user-guide/README.md)
- **Support Portal**: [support.nexus.ai](https://support.nexus.ai)
- **Email**: support@nexus.ai

---

## 📦 Deployment Options

The Toolkit supports deploying capabilities to multiple cloud providers and environments:

### Supported Platforms

| Platform | Status | Documentation |
|----------|--------|---------------|
| **AWS** | ✅ Fully Supported | [AWS Configuration Guide](doc/user-guide/04-aws-configuration.md) |
| **Azure** | 🔜 Coming Soon | Planned for Q2 2026 |
| **GCP** | 🔜 Coming Soon | Planned for Q3 2026 |
| **Kubernetes** | 🔜 Coming Soon | Planned for Q4 2026 |
| **On-Premise** | 🔜 Coming Soon | Planned for 2027 |

### AWS Deployment Architectures

**Frontend Options:**
- **CloudFront + S3**: Static hosting with global CDN (recommended)
- **AWS Amplify**: Managed hosting with CI/CD integration
- **Skip Frontend**: Deploy backend only

**Backend Options:**
- **ECS Fargate**: Serverless containers with auto-scaling (recommended)
- **EKS (Kubernetes)**: Full Kubernetes orchestration
- **EC2 Instances**: Traditional virtual machines
- **Skip Backend**: Deploy frontend only

See [Deployment Strategy Guide](DEPLOYMENT_STRATEGY_GUIDE.md) for details.

---

## 🔐 Security & Compliance

### Security Features

- **Multi-Factor Authentication**: TOTP, SMS, email-based MFA
- **Role-Based Access Control**: Administrator, Operator, Viewer roles
- **SSO Integration**: SAML 2.0, OAuth 2.0, OpenID Connect support
- **Encryption**: AES-256 at rest, TLS 1.2+ in transit
- **Audit Logging**: Complete trail of all user actions
- **Secrets Management**: AWS Secrets Manager integration
- **License Enforcement**: Cryptographic license validation
- **Password Policies**: Complexity requirements, rotation, history

### Compliance

The Toolkit is designed to meet:
- **SOC 2 Type II** requirements
- **GDPR** data handling regulations
- **HIPAA** compliance (healthcare deployments)
- **PCI DSS** standards (payment processing)
- **AWS Well-Architected Framework** best practices

See [AWS WAFR Compliance](doc/capability-arcitechture/AWS-WAFR-COMPLIANCE.md) for details.

---

## 📊 Monitoring & Operations

### Built-in Monitoring

- **Real-Time Dashboards**: Live deployment status and health
- **CloudWatch Integration**: Metrics, logs, and alarms
- **Health Checks**: Automated health verification every 5 minutes
- **Alert Notifications**: Email, SMS, push notifications
- **Audit Logs**: Complete history with tamper-evident exports
- **Performance Metrics**: Deployment times, success rates, resource usage

### Operational Management

- **Update Management**: Self-service patching and version updates
- **Backup & Recovery**: Automated backups with point-in-time recovery
- **Disaster Recovery**: Multi-region failover capabilities
- **Cost Tracking**: AWS cost allocation and optimization
- **Capacity Planning**: Resource utilization and scaling recommendations

---

## 🚢 Release Management

### Current Version

**Version 1.0.0** - January 2026

See [Release Notes](doc/release-notes/) for version history and changelog.

### Versioning

We follow [Semantic Versioning](https://semver.org/):
- **MAJOR** version: Incompatible API changes
- **MINOR** version: Backward-compatible functionality additions
- **PATCH** version: Backward-compatible bug fixes

### Release Cycle

- **Major releases**: Quarterly (Q1, Q2, Q3, Q4)
- **Minor releases**: Monthly (feature additions)
- **Patch releases**: As needed (critical bug fixes)
- **Security patches**: Immediately (critical vulnerabilities)

---

## 🤝 Contributing

This is a proprietary project. Internal contributors should follow:

1. **Branch Strategy**: `main` (production), `develop` (integration), `feature/*` (features)
2. **Code Review**: All PRs require 2 approvals
3. **Testing**: Minimum 80% code coverage required
4. **Documentation**: Update docs for all feature changes
5. **Changelog**: Add entries to release notes

---

## 📝 License

**Proprietary - Nexus AI**

This software is proprietary and confidential. Unauthorized copying, modification, distribution, or use is strictly prohibited.

© 2026 Nexus AI. All rights reserved.

---

## 🆘 Support

### For Customers

- **Email**: support@nexus.ai
- **Support Portal**: [support.nexus.ai](https://support.nexus.ai)
- **Phone**: +1-800-NEXUS-AI (M-F 9AM-5PM EST)
- **Emergency**: 24/7 support for production issues

### For Developers

- **Internal Wiki**: [wiki.nexus.internal](https://wiki.nexus.internal)
- **Slack**: #toolkit-development
- **JIRA**: [jira.nexus.ai/TOOLKIT](https://jira.nexus.ai/TOOLKIT)

---

## 🔗 Additional Resources

### External Links

- **Website**: [www.nexus.ai](https://www.nexus.ai)
- **Blog**: [blog.nexus.ai](https://blog.nexus.ai)
- **Developer Portal**: [developers.nexus.ai](https://developers.nexus.ai)

### Internal Resources

- **Product Roadmap**: See Product Management
- **Architecture Decisions**: See [Solution Architecture](doc/solution-architecture.md)
- **API Documentation**: http://localhost:8001/docs (when running)

---

## 📈 Success Metrics

### Customer Success
- ⏱️ **Time to First Deployment**: < 1 hour from license activation
- ✅ **Deployment Success Rate**: > 95%
- 😊 **Customer Satisfaction**: > 4.5/5
- 📈 **Net Promoter Score**: > 50
- 🔄 **Annual Retention**: > 85%

### Technical Performance
- ⚡ **Deployment Time**: < 30 minutes average
- 🎯 **API Response Time**: < 500ms P95
- 📊 **Uptime**: > 99.9%
- 🔒 **Security Incidents**: 0 critical

---

**Built with ❤️ by the Nexus AI Engineering Team**

For questions or feedback, contact: toolkit-team@nexus.ai
