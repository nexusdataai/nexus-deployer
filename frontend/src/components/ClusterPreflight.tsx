/**
 * Cluster Pre-flight wizard step - the SINGLE pre-deployment screen
 * for the Pure-EKS path.
 *
 * Mounts after EKS_CLUSTER_SELECTION. Runs the cluster-related
 * pipeline steps (1-4 + 6 of the 10-step pipeline) plus a Container
 * images section and an Existing-deployment detection that ran
 * separately in the legacy ECS-era PermissionVerification screen.
 *
 * Continue navigates directly to STRATEGY_SELECTION (when an existing
 * capability is detected) or DEPLOYMENT_EXECUTION (fresh) - skipping
 * PERMISSION_VERIFICATION, which was redundant for the Pure-EKS path
 * (account-access / IAM-permissions / network-resources / EKS-access
 * are all already covered here or implicitly by the AWS sign-in step).
 */
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useWizard } from '../context/WizardContext';
import { WizardStep, StackDetectionResult, DeploymentStrategy } from '../types/wizard';
import { API_BASE } from '../lib/apiBase';
import {
  eksPipelineApi,
  ClusterReadinessReport,
  ControllerInstallReport,
  IRSAMappingReport,
  IAMAuditReport,
  NetworkConfigReport,
  PipelineCheck,
  OverallStatus,
} from '../services/eksPipelineApi';
import { deploymentApi } from '../services/api';

interface CardState<T> {
  loading: boolean;
  error: string | null;
  report: T | null;
}

const initial = <T,>(): CardState<T> => ({ loading: false, error: null, report: null });

const STATUS_COLOR: Record<string, string> = {
  pass: 'text-green-700 bg-green-50 border-green-300',
  warn: 'text-amber-700 bg-amber-50 border-amber-300',
  fail: 'text-red-700 bg-red-50 border-red-300',
  skipped: 'text-gray-500 bg-gray-50 border-gray-200',
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => (
  <span className={`px-2 py-0.5 text-xs font-medium uppercase rounded border ${STATUS_COLOR[status] || STATUS_COLOR.warn}`}>
    {status}
  </span>
);

const CheckRow: React.FC<{ check: PipelineCheck }> = ({ check }) => (
  <div className="border border-gray-200 rounded-lg p-3 mb-2">
    <div className="flex items-center justify-between gap-3 mb-1">
      <span className="font-medium text-gray-800">{check.label}</span>
      <StatusBadge status={check.status} />
    </div>
    {check.detail && <div className="text-sm text-gray-600">{check.detail}</div>}
    {check.remediation && (
      <div className="mt-2 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded p-2 whitespace-pre-wrap">
        <span className="font-semibold">Remediation: </span>{check.remediation}
      </div>
    )}
  </div>
);

const overallOf = (...statuses: (OverallStatus | undefined)[]): OverallStatus => {
  if (statuses.includes('fail')) return 'fail';
  if (statuses.includes('warn')) return 'warn';
  return 'pass';
};

interface ImageReport {
  overall: OverallStatus;
  checks: PipelineCheck[];
  can_proceed: boolean;
}

const ClusterPreflight: React.FC = () => {
  const { state, setStep, setDetectionResult } = useWizard();
  const cluster = state.eksConfig?.clusterName || '';
  const namespace = state.eksConfig?.namespace || '';
  const iamMode = (state.eksConfig?.iamMode ?? 'managed') as 'managed' | 'preprovisioned';
  const appRoleArn =
    iamMode === 'preprovisioned' ? state.eksConfig?.appRoleArn : undefined;
  const awsSessionId = state.awsConfig?.aws_session_id || undefined;

  const [readiness, setReadiness] = useState<CardState<ClusterReadinessReport>>(initial);
  const [controllers, setControllers] = useState<CardState<ControllerInstallReport>>(initial);
  const [irsa, setIrsa] = useState<CardState<IRSAMappingReport>>(initial);
  const [iamAudit, setIamAudit] = useState<CardState<IAMAuditReport>>(initial);
  const [network, setNetwork] = useState<CardState<NetworkConfigReport>>(initial);
  const [images, setImages] = useState<CardState<ImageReport>>(initial);
  const [continuing, setContinuing] = useState(false);
  const [continueError, setContinueError] = useState<string | null>(null);

  const runReadiness = async () => {
    setReadiness({ loading: true, error: null, report: null });
    try {
      const r = await eksPipelineApi.readiness(cluster, iamMode, awsSessionId);
      setReadiness({ loading: false, error: null, report: r });
    } catch (e: any) {
      setReadiness({ loading: false, error: e?.message || String(e), report: null });
    }
  };
  const runControllers = async () => {
    setControllers({ loading: true, error: null, report: null });
    try {
      const r = await eksPipelineApi.installControllers(cluster, iamMode, awsSessionId);
      setControllers({ loading: false, error: null, report: r });
    } catch (e: any) {
      setControllers({ loading: false, error: e?.message || String(e), report: null });
    }
  };
  const runIrsa = async () => {
    setIrsa({ loading: true, error: null, report: null });
    try {
      const r = await eksPipelineApi.verifyIrsa(
        cluster, iamMode, namespace || undefined, appRoleArn, awsSessionId,
      );
      setIrsa({ loading: false, error: null, report: r });
    } catch (e: any) {
      setIrsa({ loading: false, error: e?.message || String(e), report: null });
    }
  };
  const runIamAudit = async () => {
    setIamAudit({ loading: true, error: null, report: null });
    try {
      const r = await eksPipelineApi.iamAudit(
        cluster, iamMode, namespace || undefined, appRoleArn, awsSessionId,
      );
      setIamAudit({ loading: false, error: null, report: r });
    } catch (e: any) {
      setIamAudit({ loading: false, error: e?.message || String(e), report: null });
    }
  };
  const runNetwork = async () => {
    setNetwork({ loading: true, error: null, report: null });
    try {
      const r = await eksPipelineApi.applyNetworkConfig(cluster, 120, awsSessionId);
      setNetwork({ loading: false, error: null, report: r });
    } catch (e: any) {
      setNetwork({ loading: false, error: e?.message || String(e), report: null });
    }
  };

  const runImages = async () => {
    setImages({ loading: true, error: null, report: null });
    const frontendUri = state.selectedCapability?.eks_artifacts?.frontend_ecr_uri || '';
    const backendUri = state.selectedCapability?.eks_artifacts?.backend_ecr_uri || '';
    const requiresFrontend = !!state.selectedCapability?.requirements?.frontend;
    const requiresBackend = !!state.selectedCapability?.requirements?.backend;

    const verifyImage = async (label: string, uri: string, required: boolean): Promise<PipelineCheck> => {
      if (!required) {
        return { name: label, label, status: 'skipped', detail: 'Not required for this capability' };
      }
      if (!uri) {
        return {
          name: label,
          label,
          status: 'fail',
          detail: 'No ECR URI configured on this capability',
          remediation:
            'Set eks_artifacts.frontend_ecr_uri / eks_artifacts.backend_ecr_uri on the capability before deploying.',
        };
      }
      try {
        const resp = await axios.post(`${API_BASE}/api/aws/verify-artifact`, {
          aws_session_id: awsSessionId,
          artifact_type: 'backend', // ECR verifier handles both frontend + backend image manifests under this type
          ecr_uri: uri,
        });
        const sizeMb = resp.data?.size_mb;
        const pushedAt = resp.data?.pushed_at;
        const tag = uri.split(':').pop();
        const tail = [
          `image: ${uri.split('/').pop()}`,
          tag ? `tag=${tag}` : null,
          sizeMb ? `size=${sizeMb} MB` : null,
          pushedAt ? `pushed=${new Date(pushedAt).toLocaleString()}` : null,
        ].filter(Boolean).join(' · ');
        return { name: label, label, status: 'pass', detail: tail };
      } catch (err: any) {
        return {
          name: label,
          label,
          status: 'fail',
          detail: err?.response?.data?.detail || err?.message || 'verify-artifact failed',
          remediation:
            'Confirm the ECR repository / tag exists in this region and the wizard session role has ecr:DescribeImages.',
        };
      }
    };

    try {
      const [feCheck, beCheck] = await Promise.all([
        verifyImage('Frontend container image', frontendUri, requiresFrontend),
        verifyImage('Backend container image', backendUri, requiresBackend),
      ]);
      const checks = [feCheck, beCheck];
      const overall: OverallStatus = checks.some((c) => c.status === 'fail')
        ? 'fail'
        : checks.some((c) => c.status === 'warn')
          ? 'warn'
          : 'pass';
      const can_proceed = !checks.some((c) => c.status === 'fail');
      setImages({ loading: false, error: null, report: { overall, checks, can_proceed } });
    } catch (e: any) {
      setImages({ loading: false, error: e?.message || String(e), report: null });
    }
  };

  useEffect(() => {
    if (!cluster) return;
    runReadiness();
    runControllers();
    runIrsa();
    runIamAudit();
    runNetwork();
    runImages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cluster, iamMode]);

  const overall = overallOf(
    readiness.report?.overall,
    controllers.report?.overall,
    irsa.report?.overall,
    iamAudit.report?.overall,
    network.report?.overall,
    images.report?.overall,
  );
  const canContinue =
    !readiness.loading && !controllers.loading && !irsa.loading &&
    !iamAudit.loading && !network.loading && !images.loading && !continuing &&
    !!readiness.report?.can_proceed &&
    !!controllers.report?.can_proceed &&
    !!irsa.report?.can_proceed &&
    !!iamAudit.report?.can_proceed &&
    !!network.report?.can_proceed &&
    !!images.report?.can_proceed;

  // On Continue: run capability/CR detection (the legacy
  // PermissionVerification used to do this), persist it in wizard
  // context, and route directly to STRATEGY_SELECTION (existing
  // capability) or DEPLOYMENT_EXECUTION (fresh).
  const handleContinue = async () => {
    setContinueError(null);
    setContinuing(true);
    try {
      const capabilityName = state.selectedCapability?.name || '';
      const environment = state.selectedEnvironment || '';
      const region = state.awsConfig?.region || '';
      let detection: StackDetectionResult;
      try {
        detection = await deploymentApi.detectExistingStacks(
          capabilityName, environment, region, awsSessionId,
        );
      } catch (err: any) {
        // Detection failure should not block deploy - treat as fresh.
        detection = {
          capability_name: capabilityName,
          environment,
          region,
          has_existing_stacks: false,
          has_failed_stacks: false,
          has_in_progress_stacks: false,
          is_updatable: false,
          stacks_found: [],
          recommended_strategy: DeploymentStrategy.CLEAN_DEPLOY,
          recommendation_reason: `Detection failed: ${err?.response?.data?.detail || err?.message || 'unknown'}. Proceeding as clean deploy.`,
          detection_timestamp: new Date().toISOString(),
        };
      }
      setDetectionResult(detection);
      await new Promise((r) => setTimeout(r, 50));
      if (detection.has_existing_stacks) {
        setStep(WizardStep.STRATEGY_SELECTION);
      } else {
        setStep(WizardStep.DEPLOYMENT_EXECUTION);
      }
    } catch (err: any) {
      setContinueError(err?.message || 'Failed to advance from pre-flight');
    } finally {
      setContinuing(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">Pre-deployment Verification</h1>
        <p className="text-sm text-gray-600">
          Verifies the target EKS cluster is ready for the Nexus AI Operator and the
          capability's container images are pullable. AWS account access, network
          baseline, and IAM-permission catalogs are not re-checked here - the
          landing-zone cluster is assumed to be properly configured by the platform
          team. Continue runs existing-capability detection and routes to deploy.
        </p>
        <div className="mt-2 flex items-center gap-3">
          <span className="text-sm text-gray-600">Overall:</span>
          <StatusBadge status={overall} />
        </div>
      </div>

      <Section
        index={1}
        title="Cluster readiness"
        state={readiness}
        onRerun={runReadiness}
        renderReport={(r) => r.checks.map((c) => <CheckRow key={c.name} check={c} />)}
      />
      <Section
        index={2}
        title={`Controllers (ALB + EBS CSI)${iamMode === 'preprovisioned' ? ' - verify only' : ''}`}
        state={controllers}
        onRerun={runControllers}
        renderReport={(r) => (
          <>
            <CheckRow check={r.alb_controller} />
            <CheckRow check={r.ebs_csi_driver} />
          </>
        )}
      />
      <Section
        index={3}
        title="IRSA mapping"
        state={irsa}
        onRerun={runIrsa}
        renderReport={(r) => r.roles.map((c) => <CheckRow key={c.name} check={c} />)}
      />
      <Section
        index={4}
        title={`IAM audit (${iamMode})`}
        state={iamAudit}
        onRerun={runIamAudit}
        renderReport={(r) => r.checks.map((c) => <CheckRow key={c.name} check={c} />)}
      />
      <Section
        index={5}
        title="Container images"
        state={images}
        onRerun={runImages}
        renderReport={(r) => r.checks.map((c) => <CheckRow key={c.name} check={c} />)}
      />
      <Section
        index={6}
        title="VPC private endpoints"
        state={network}
        onRerun={runNetwork}
        renderReport={(r) => (
          <>
            <CheckRow
              check={{
                name: 'network_config',
                label: `VPC private endpoints (${r.healthy_endpoints}/${r.total_endpoints} available)`,
                status:
                  r.overall === 'pass' ? 'pass' :
                  r.overall === 'warn' ? 'warn' : 'fail',
                detail: `phase=${r.phase}. ${r.message}`,
              }}
            />
            {r.endpoints.map((epRaw) => {
              const ep = epRaw as {
                service: string;
                service_name?: string;
                type?: string;
                state?: string;
                created?: boolean;
                existed?: boolean;
                via?: string;
                endpoint_id?: string;
                prefix_list_id?: string;
                subnets?: string[];
                error?: string;
              };
              const isError = !!ep.error || ep.state === 'error' || ep.state === 'failed';
              const isHealthy = !isError && (
                ep.existed === true ||
                ep.state === 'available' || ep.state === 'Available'
              );
              const isPending = !isError && !isHealthy && (
                ep.state === 'pending' || ep.state === 'pendingAcceptance' ||
                ep.state === 'Pending'
              );
              let provenance: string;
              if (ep.created) {
                provenance = 'created now';
              } else if (ep.existed) {
                if (ep.via === 'prefix-list-route') {
                  provenance = `pre-existing via prefix-list ${ep.prefix_list_id ?? ''}`.trim();
                } else if (ep.via === 'dns-overlay') {
                  provenance = 'pre-existing via private-DNS overlay';
                } else if (ep.via === 'already-exists' || ep.via === 'vpc-endpoint-recheck') {
                  provenance = 'pre-existing (detected on create)';
                } else {
                  provenance = 'pre-existing';
                }
              } else {
                provenance = 'create attempted';
              }
              return (
                <CheckRow
                  key={ep.service}
                  check={{
                    name: `endpoint_${ep.service}`,
                    label: ep.service_name || `com.amazonaws.<region>.${ep.service}`,
                    status: isError ? 'fail' : isHealthy ? 'pass' : isPending ? 'warn' : 'warn',
                    detail: [
                      ep.type,
                      `state=${ep.state || 'unknown'}`,
                      ep.endpoint_id ? `id=${ep.endpoint_id}` : null,
                      provenance,
                    ].filter(Boolean).join(' · '),
                    remediation: ep.error,
                  }}
                />
              );
            })}
          </>
        )}
      />

      {continueError && (
        <div className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">
          {continueError}
        </div>
      )}
      <div className="flex justify-between mt-8">
        <button
          onClick={() => setStep(WizardStep.EKS_CLUSTER_SELECTION)}
          className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
        >
          Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!canContinue}
          className={`px-6 py-2 rounded-lg font-medium ${
            canContinue
              ? 'bg-blue-600 text-white hover:bg-blue-700'
              : 'bg-gray-200 text-gray-500 cursor-not-allowed'
          }`}
        >
          {continuing ? 'Detecting existing capability...' : 'Continue'}
        </button>
      </div>
    </div>
  );
};

interface SectionProps<T> {
  index: number;
  title: string;
  state: CardState<T>;
  onRerun: () => void;
  renderReport: (r: T) => React.ReactNode;
}

function Section<T>({ index, title, state, onRerun, renderReport }: SectionProps<T>) {
  return (
    <div className="border border-gray-200 rounded-lg p-4 mb-4 bg-white">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-gray-800">
          {index}. {title}
        </h2>
        <button
          onClick={onRerun}
          disabled={state.loading}
          className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          {state.loading ? 'Running...' : 'Re-run'}
        </button>
      </div>
      {state.error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-2">
          {state.error}
        </div>
      )}
      {state.report ? renderReport(state.report) : (
        state.loading ? <div className="text-sm text-gray-500">Running checks...</div> :
        <div className="text-sm text-gray-500">Not run yet.</div>
      )}
    </div>
  );
}

export default ClusterPreflight;
