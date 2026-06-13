/**
 * Full capability inspection panel (step 10 of the EKS pipeline).
 *
 * Renders the report from /api/eks/pipeline/.../capability/.../inspect
 * as collapsible sections. Healthy sections collapse by default;
 * failing or warning ones expand so the user sees problems first.
 */
import React, { useEffect, useState } from 'react';
import {
  eksPipelineApi,
  CapabilityInspectionReport,
  InspectionSection,
  CheckStatus,
} from '../services/eksPipelineApi';

interface Props {
  clusterName: string;
  crName: string;
  namespace: string;
  capabilityName: string;
  environment: string;
  awsSessionId?: string;
  onClose?: () => void;
}

const STATUS_COLOR: Record<CheckStatus, string> = {
  pass: 'text-green-700 bg-green-50 border-green-300',
  warn: 'text-amber-700 bg-amber-50 border-amber-300',
  fail: 'text-red-700 bg-red-50 border-red-300',
  skipped: 'text-gray-500 bg-gray-50 border-gray-200',
};

const Badge: React.FC<{ status: string }> = ({ status }) => (
  <span
    className={`px-2 py-0.5 text-xs font-medium uppercase rounded border ${
      STATUS_COLOR[(status as CheckStatus) || 'warn'] || STATUS_COLOR.warn
    }`}
  >
    {status}
  </span>
);

const InspectCapability: React.FC<Props> = ({
  clusterName,
  crName,
  namespace,
  capabilityName,
  environment,
  awsSessionId,
  onClose,
}) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<CapabilityInspectionReport | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await eksPipelineApi.inspect(
        clusterName, crName, namespace, capabilityName, environment, awsSessionId,
      );
      setReport(r);
      // Auto-expand sections that need attention.
      const init: Record<string, boolean> = {};
      for (const s of r.sections) {
        init[s.name] = s.status === 'fail' || s.status === 'warn';
      }
      setExpanded(init);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterName, crName, namespace, capabilityName, environment]);

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 mb-1">Capability Inspection</h1>
          <p className="text-sm text-gray-600">
            {capabilityName} ({environment}) on {clusterName} - 17 sections,
            mirroring kube-operator/inspect-capability.sh.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={run}
            disabled={loading}
            className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {loading ? 'Inspecting...' : 'Re-run'}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 mb-4">
          {error}
        </div>
      )}

      {report && (
        <>
          <div className="flex items-center gap-3 mb-4">
            <span className="text-sm text-gray-600">Overall:</span>
            <Badge status={report.overall} />
            <span className="text-xs text-gray-500">
              {report.sections.filter(s => s.status === 'pass').length} pass,
              {' '}{report.sections.filter(s => s.status === 'warn').length} warn,
              {' '}{report.sections.filter(s => s.status === 'fail').length} fail
            </span>
          </div>

          {report.sections.map((s) => (
            <SectionBlock
              key={s.name}
              section={s}
              expanded={!!expanded[s.name]}
              onToggle={() => setExpanded(prev => ({ ...prev, [s.name]: !prev[s.name] }))}
            />
          ))}
        </>
      )}

      {loading && !report && (
        <div className="text-sm text-gray-500">Running 17 inspection sections...</div>
      )}
    </div>
  );
};

interface SectionBlockProps {
  section: InspectionSection;
  expanded: boolean;
  onToggle: () => void;
}

const SectionBlock: React.FC<SectionBlockProps> = ({ section, expanded, onToggle }) => (
  <div className="border border-gray-200 rounded-lg mb-3 bg-white overflow-hidden">
    <button
      onClick={onToggle}
      className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50"
    >
      <div className="flex items-center gap-3">
        <span className="text-gray-400 text-sm">{expanded ? '▼' : '▶'}</span>
        <span className="font-medium text-gray-800">{section.label}</span>
        <Badge status={section.status} />
      </div>
      <span className="text-xs text-gray-500">{section.summary}</span>
    </button>
    {expanded && (
      <div className="px-4 pb-3 border-t border-gray-100">
        {section.rows.length === 0 ? (
          <div className="text-sm text-gray-500 py-2">No rows.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm mt-2">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-500 border-b">
                  {Object.keys(section.rows[0] || {}).slice(0, 6).map((k) => (
                    <th key={k} className="py-1 pr-3">{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {section.rows.map((row, idx) => (
                  <tr key={idx} className="border-b border-gray-50 last:border-b-0">
                    {Object.keys(section.rows[0] || {}).slice(0, 6).map((k) => (
                      <td key={k} className="py-1 pr-3 align-top text-gray-700">
                        {formatCell(row[k])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {section.raw && (
          <pre className="mt-2 text-xs bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto">
            {section.raw}
          </pre>
        )}
      </div>
    )}
  </div>
);

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

export default InspectCapability;
