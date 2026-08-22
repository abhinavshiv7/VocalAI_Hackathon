'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

type Target = {
  id: string;
  name: string;
  environment: string;
  host: string;
  port: number;
  authorized: boolean;
  allowed_tools: string[];
  approved_paths: string[];
};

type Evidence = {
  id: string;
  hypothesis_id: string | null;
  source: string;
  observation: string;
  severity: string;
  kind: string;
  created_at: string;
};

type Hypothesis = {
  id: string;
  title: string;
  description: string;
  confidence: number;
  status: string;
  required_evidence: string[];
  critic_decision: null | {
    decision: string;
    reason: string;
    missing_evidence: string[];
    contradictions: string[];
  };
};

type Finding = {
  id: string;
  title: string;
  severity: string;
  confidence: number;
  status: string;
  evidence_refs: string[];
  recommendation: string;
};

type Investigation = {
  id: string;
  target_id: string;
  status: string;
  degraded_mode: boolean;
  summary: string;
  model_calls: number;
  tool_calls: number;
  estimated_cost_usd: number;
  created_at: string;
  completed_at: string | null;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  findings: Finding[];
  tool_executions: Array<{
    id: string;
    tool: string;
    status: string;
    input_summary: string;
    result_summary: string;
    latency_ms: number;
  }>;
  events: Array<{
    id: number;
    event_type: string;
    message: string;
    created_at: string;
  }>;
};

type Evaluation = {
  scenarios: number;
  success_rate: number;
  false_positives: number;
  graceful_failure_rate: number;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const pipeline = ['Observe', 'Hypothesize', 'Investigate', 'Critique', 'Decide'];
const failureModes = [
  { value: 'none', label: 'Happy path', kind: 'none', subject: null },
  { value: 'tool', label: 'Fail web tool', kind: 'tool', subject: 'web_inspection' },
  { value: 'investigator', label: 'Kill Investigator', kind: 'model', subject: 'investigator' },
  { value: 'critic', label: 'Kill Critic', kind: 'model', subject: 'critic' },
  { value: 'malformed', label: 'Malformed Critic JSON', kind: 'malformed_output', subject: 'critic' },
];

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

function statusTone(status: string) {
  if (status === 'VALIDATED' || status === 'SUCCEEDED' || status === 'COMPLETED') return 'green';
  if (status === 'REJECTED') return 'blue';
  if (status.includes('HUMAN') || status === 'FAILED') return 'amber';
  return 'neutral';
}

function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    green: 'border-[#8ff4b5]/25 bg-[#8ff4b5]/10 text-[#9af7bd]',
    blue: 'border-[#8bc5ff]/25 bg-[#8bc5ff]/10 text-[#a8d6ff]',
    amber: 'border-[#ffcf7a]/25 bg-[#ffcf7a]/10 text-[#ffd48b]',
    neutral: 'border-white/10 bg-white/[.04] text-[#aebfb8]',
  };
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[.12em] ${tones[tone]}`}>{children}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-2xl border border-dashed border-white/10 px-5 py-10 text-center text-sm text-[#71877e]">{text}</div>;
}

export default function Home() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [history, setHistory] = useState<Investigation[]>([]);
  const [current, setCurrent] = useState<Investigation | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [targetId, setTargetId] = useState('lab-web-01');
  const [showTargetForm, setShowTargetForm] = useState(false);
  const [targetForm, setTargetForm] = useState({ name: '', environment: 'authorized-lab', baseUrl: '', paths: '/admin, /api/status', attested: false });
  const [failureMode, setFailureMode] = useState('none');
  const [activeTab, setActiveTab] = useState<'hypotheses' | 'evidence' | 'audit'>('hypotheses');
  const [workspaceView, setWorkspaceView] = useState<'investigation' | 'evaluation' | 'audit'>('investigation');
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');

  const loadWorkspace = useCallback(async () => {
    try {
      const [targetData, investigationData, evaluationData] = await Promise.all([
        request<Target[]>('/api/targets'),
        request<Investigation[]>('/api/investigations'),
        request<Evaluation>('/api/evaluations'),
      ]);
      setTargets(targetData);
      setHistory(investigationData);
      setEvaluation(evaluationData);
      setConnected(true);
      if (investigationData[0]) setCurrent(investigationData[0]);
    } catch (caught) {
      setConnected(false);
      setError(caught instanceof Error ? caught.message : 'Backend unavailable');
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadWorkspace(), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  const runInvestigation = async () => {
    setLoading(true);
    setError('');
    try {
      const mode = failureModes.find((item) => item.value === failureMode) ?? failureModes[0];
      await request('/api/debug/inject-failure', {
        method: 'POST',
        body: JSON.stringify({ kind: mode.kind, subject: mode.subject, enabled: mode.kind !== 'none' }),
      });
      const created = await request<Investigation>('/api/investigations', {
        method: 'POST',
        body: JSON.stringify({ target_id: targetId }),
      });
      setCurrent(created);
      const completed = await request<Investigation>(`/api/investigations/${created.id}/start`, { method: 'POST' });
      setCurrent(completed);
      setHistory((previous) => [completed, ...previous.filter((item) => item.id !== completed.id)]);
      setConnected(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Investigation failed');
    } finally {
      setLoading(false);
    }
  };

  const registerTarget = async () => {
    setError('');
    try {
      const target = await request<Target>('/api/targets', {
        method: 'POST',
        body: JSON.stringify({
          name: targetForm.name,
          environment: targetForm.environment,
          base_url: targetForm.baseUrl,
          approved_paths: targetForm.paths.split(',').map((path) => path.trim()).filter(Boolean),
          authorization_attested: targetForm.attested,
        }),
      });
      setTargets((items) => [...items, target]);
      setTargetId(target.id);
      setShowTargetForm(false);
      setTargetForm({ name: '', environment: 'authorized-lab', baseUrl: '', paths: '/admin, /api/status', attested: false });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not register the target.');
    }
  };

  const acknowledgeReview = async () => {
    if (!current) return;
    try {
      const updated = await request<Investigation>(`/api/investigations/${current.id}/approve`, { method: 'POST' });
      setCurrent(updated);
      setHistory((previous) => previous.map((item) => item.id === updated.id ? updated : item));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not acknowledge review');
    }
  };

  const stats = useMemo(() => ({
    validated: current?.findings.filter((item) => item.status === 'VALIDATED').length ?? 0,
    review: current?.findings.filter((item) => item.status === 'NEEDS_HUMAN_REVIEW').length ?? 0,
    rejected: current?.hypotheses.filter((item) => item.status === 'REJECTED').length ?? 0,
  }), [current]);

  return (
    <main className="min-h-screen bg-[#07110f] text-[#e9f2ed]">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#07110f]/90 px-5 py-4 backdrop-blur-xl lg:px-8">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#9af7bd] font-black text-[#07110f]">S</span>
            <div>
              <p className="font-semibold tracking-tight">SentinelLoop</p>
              <p className="hidden text-[10px] uppercase tracking-[0.18em] text-[#71877e] sm:block">Authorized security validation</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${connected ? 'bg-[#9af7bd] shadow-[0_0_12px_#9af7bd]' : 'bg-[#ffcf7a]'}`} />
            <span className="text-xs text-[#9cb0a7]">{connected ? 'Control plane online' : 'Preview mode'}</span>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1600px] lg:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="border-b border-white/10 px-5 py-5 lg:min-h-[calc(100vh-73px)] lg:border-b-0 lg:border-r lg:px-4">
          <p className="px-2 text-[10px] font-bold uppercase tracking-[.16em] text-[#567066]">Workspace</p>
          <nav className="mt-3 grid grid-cols-3 gap-2 lg:grid-cols-1" aria-label="Dashboard navigation">
            {(['Investigation', 'Evaluation', 'Audit trail'] as const).map((item, index) => {
              const view = index === 0 ? 'investigation' : index === 1 ? 'evaluation' : 'audit';
              return <button key={item} onClick={() => setWorkspaceView(view)} className={`rounded-xl px-3 py-2.5 text-left text-sm ${workspaceView === view ? 'bg-white/[.07] text-white' : 'text-[#82998f] hover:bg-white/[.035]'}`}>
                <span className="mr-2 text-[#9af7bd]">{['◉', '⌁', '≡'][index]}</span>{item}
              </button>;
            })}
          </nav>

          <div className="mt-7 hidden lg:block">
            <div className="flex items-center justify-between px-2">
              <p className="text-[10px] font-bold uppercase tracking-[.16em] text-[#567066]">Recent runs</p>
              <span className="text-[10px] text-[#567066]">{history.length}</span>
            </div>
            <div className="mt-3 space-y-2">
              {history.slice(0, 6).map((item) => (
                <button key={item.id} onClick={() => setCurrent(item)} className={`w-full rounded-xl border p-3 text-left transition ${current?.id === item.id ? 'border-[#9af7bd]/25 bg-[#9af7bd]/[.07]' : 'border-transparent hover:bg-white/[.035]'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-[#aebfb8]">{item.id.slice(0, 13)}</span>
                    <span className={`h-1.5 w-1.5 rounded-full ${item.status === 'HUMAN_REVIEW' ? 'bg-[#ffcf7a]' : 'bg-[#9af7bd]'}`} />
                  </div>
                  <p className="mt-1 truncate text-[11px] text-[#5f786e]">{item.summary || item.status}</p>
                </button>
              ))}
              {!history.length && <p className="px-2 py-4 text-xs text-[#5f786e]">No runs yet.</p>}
            </div>
          </div>

          <div className="mt-8 hidden rounded-2xl border border-[#9af7bd]/15 bg-[#9af7bd]/[.045] p-4 lg:block">
            <p className="text-[10px] font-bold uppercase tracking-[.14em] text-[#9af7bd]">Safety invariant</p>
            <p className="mt-2 text-xs leading-5 text-[#91a69d]">No finding validates unless both the Investigator and Critic complete successfully.</p>
          </div>
        </aside>

        <div className="min-w-0 px-5 py-6 lg:px-8 lg:py-8">
          <section className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_370px]">
            <div className="overflow-hidden rounded-[26px] border border-white/10 bg-[#0b1916]">
              <div className="relative p-6 sm:p-8">
                <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[#39d98a]/10 blur-3xl" />
                <div className="relative flex flex-col justify-between gap-7 xl:flex-row xl:items-end">
                  <div>
                    <div className="mb-4 flex flex-wrap items-center gap-2">
                      <Badge tone="green">Authorized lab</Badge>
                      <Badge>Read-only operations</Badge>
                    </div>
                    <h1 className="max-w-3xl text-3xl font-semibold leading-tight tracking-[-0.04em] sm:text-[42px]">Evidence first. Conclusions last.</h1>
                    <p className="mt-3 max-w-2xl text-sm leading-6 text-[#91a69d]">Run a constrained investigation, inspect every evidence hop, and see exactly where the independent critic agrees—or refuses.</p>
                  </div>
                  <button
                    onClick={runInvestigation}
                    disabled={loading || !targets.length}
                    className="shrink-0 rounded-xl bg-[#9af7bd] px-5 py-3.5 text-sm font-bold text-[#07110f] shadow-[0_10px_30px_rgba(89,226,141,.12)] transition hover:bg-[#baffcf] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {loading ? 'Investigation running…' : 'Run investigation →'}
                  </button>
                </div>
              </div>
              <div className="grid gap-px border-t border-white/10 bg-white/10 sm:grid-cols-2">
                <div className="bg-[#0a1714] px-6 py-4">
                  <span className="text-[10px] font-bold uppercase tracking-[.14em] text-[#567066]">Authorized target</span>
                  <select value={targetId} onChange={(event) => setTargetId(event.target.value)} className="mt-1 block w-full bg-transparent text-sm text-[#dbe8e2] outline-none">
                    {targets.length ? targets.map((target) => <option key={target.id} value={target.id} className="bg-[#0a1714]">{target.name}</option>) : <option className="bg-[#0a1714]">lab-web-01</option>}
                  </select>
                  <button onClick={() => setShowTargetForm((visible) => !visible)} className="mt-2 text-xs font-semibold text-[#9af7bd]">{showTargetForm ? 'Cancel target registration' : '+ Register authorized lab target'}</button>
                </div>
                <label className="bg-[#0a1714] px-6 py-4">
                  <span className="text-[10px] font-bold uppercase tracking-[.14em] text-[#567066]">Demo failure injection</span>
                  <select value={failureMode} onChange={(event) => setFailureMode(event.target.value)} className="mt-1 block w-full bg-transparent text-sm text-[#dbe8e2] outline-none">
                    {failureModes.map((mode) => <option key={mode.value} value={mode.value} className="bg-[#0a1714]">{mode.label}</option>)}
                  </select>
                </label>
              </div>
            </div>

            <aside className="rounded-[26px] border border-white/10 bg-[#0a1714] p-5">
              <div className="flex items-center justify-between">
                <p className="text-xs font-bold uppercase tracking-[.14em] text-[#82998f]">Evaluation health</p>
                <Badge tone={evaluation?.success_rate === 100 ? 'green' : 'amber'}>{evaluation ? `${evaluation.success_rate}%` : 'offline'}</Badge>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3">
                {[
                  ['Scenarios', evaluation?.scenarios ?? '—'],
                  ['False positives', evaluation?.false_positives ?? '—'],
                  ['Failure handling', evaluation ? `${evaluation.graceful_failure_rate}%` : '—'],
                  ['Cost ceiling', '$0.03'],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-white/[.07] bg-white/[.025] p-3">
                    <p className="text-xl font-semibold tracking-tight">{value}</p>
                    <p className="mt-1 text-[10px] uppercase tracking-[.12em] text-[#5f786e]">{label}</p>
                  </div>
                ))}
              </div>
              <div className="mt-4 rounded-xl bg-[#07110f] p-3 text-xs leading-5 text-[#82998f]">
                <span className="font-semibold text-[#a8bbb3]">Two-role contract:</span> Investigator proposes; Critic may validate, reject, or cap the result at human review.
              </div>
            </aside>
          </section>

          {showTargetForm && <section className="mt-5 rounded-[24px] border border-[#9af7bd]/20 bg-[#0a1714] p-5 sm:p-7">
            <Badge tone="green">Target onboarding</Badge>
            <h2 className="mt-3 text-xl font-semibold">Register an explicitly authorized lab target</h2>
            <p className="mt-2 text-sm leading-6 text-[#82998f]">Your authorization attestation is recorded when this target is added. Only the paths you enter below can be inspected, and all operations remain read-only.</p>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              <input value={targetForm.name} onChange={(event) => setTargetForm({ ...targetForm, name: event.target.value })} placeholder="Target name" className="rounded-xl border border-white/10 bg-[#07110f] px-4 py-3 text-sm outline-none" />
              <input value={targetForm.environment} onChange={(event) => setTargetForm({ ...targetForm, environment: event.target.value })} placeholder="Environment" className="rounded-xl border border-white/10 bg-[#07110f] px-4 py-3 text-sm outline-none" />
              <input value={targetForm.baseUrl} onChange={(event) => setTargetForm({ ...targetForm, baseUrl: event.target.value })} placeholder="http://approved-lab-host:3000" className="rounded-xl border border-white/10 bg-[#07110f] px-4 py-3 text-sm outline-none md:col-span-2" />
              <input value={targetForm.paths} onChange={(event) => setTargetForm({ ...targetForm, paths: event.target.value })} placeholder="/admin, /api/status" className="rounded-xl border border-white/10 bg-[#07110f] px-4 py-3 text-sm outline-none md:col-span-2" />
            </div>
            <label className="mt-4 flex items-start gap-3 text-sm text-[#aebfb8]"><input type="checkbox" checked={targetForm.attested} onChange={(event) => setTargetForm({ ...targetForm, attested: event.target.checked })} className="mt-1" />I confirm that I am authorized to assess this lab target and its listed paths.</label>
            <button disabled={!targetForm.attested || !targetForm.name || !targetForm.baseUrl} onClick={registerTarget} className="mt-5 rounded-lg bg-[#9af7bd] px-4 py-2 text-sm font-bold text-[#07110f] disabled:cursor-not-allowed disabled:opacity-40">Register target</button>
          </section>}

          {error && (
            <div role="alert" className="mt-5 flex items-start justify-between gap-4 rounded-2xl border border-[#ffcf7a]/20 bg-[#ffcf7a]/[.07] px-4 py-3 text-sm text-[#ffd48b]">
              <span>{connected ? error : `Dashboard preview is ready; connect the API at ${API_URL}. ${error}`}</span>
              <button onClick={loadWorkspace} className="shrink-0 font-semibold underline underline-offset-4">Retry</button>
            </div>
          )}

          {workspaceView === 'investigation' ? <>
          <section className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Validated', stats.validated, 'green'],
              ['Human review', stats.review, 'amber'],
              ['Rejected', stats.rejected, 'blue'],
              ['Tool / model calls', current ? `${current.tool_calls} / ${current.model_calls}` : '—', 'neutral'],
            ].map(([label, value, tone]) => (
              <div key={label} className="rounded-2xl border border-white/10 bg-[#0a1714] p-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-2xl font-semibold tracking-tight">{value}</p>
                  <span className={`h-2 w-2 rounded-full ${tone === 'green' ? 'bg-[#9af7bd]' : tone === 'amber' ? 'bg-[#ffcf7a]' : tone === 'blue' ? 'bg-[#8bc5ff]' : 'bg-[#5f786e]'}`} />
                </div>
                <p className="mt-1 text-[10px] font-bold uppercase tracking-[.13em] text-[#60786e]">{label}</p>
              </div>
            ))}
          </section>
          </> : workspaceView === 'evaluation' ? (
            <section className="mt-5 rounded-[24px] border border-white/10 bg-[#0a1714] p-5 sm:p-7">
              <Badge tone={evaluation?.success_rate === 100 ? 'green' : 'amber'}>Evaluation suite</Badge>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight">Reliability and safety evaluation</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-[#82998f]">Fixed scenarios check correct conclusions, false positives, and graceful handling of model or tool failures.</p>
              <div className="mt-6 grid gap-3 sm:grid-cols-4">
                {[
                  ['Scenarios', evaluation?.scenarios ?? '—'],
                  ['Correct conclusions', evaluation ? `${evaluation.success_rate}%` : '—'],
                  ['False positives', evaluation?.false_positives ?? '—'],
                  ['Failure handling', evaluation ? `${evaluation.graceful_failure_rate}%` : '—'],
                ].map(([label, value]) => <div key={label} className="rounded-2xl border border-white/[.08] bg-[#07110f] p-4"><p className="text-2xl font-semibold">{value}</p><p className="mt-1 text-[10px] font-bold uppercase tracking-[.13em] text-[#60786e]">{label}</p></div>)}
              </div>
              <button onClick={loadWorkspace} className="mt-6 rounded-lg border border-[#9af7bd]/25 px-4 py-2 text-xs font-semibold text-[#9af7bd]">Refresh evaluation</button>
            </section>
          ) : (
            <section className="mt-5 rounded-[24px] border border-white/10 bg-[#0a1714] p-5 sm:p-7">
              <Badge tone="neutral">Audit trail</Badge>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight">Workspace activity</h2>
              <p className="mt-2 text-sm leading-6 text-[#82998f]">Select a recent run to inspect its full policy, tool, model, and decision audit trail.</p>
              <div className="mt-6 grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
                <div className="space-y-2">{history.length ? history.map((run) => <button key={run.id} onClick={() => setCurrent(run)} className={`w-full rounded-xl border p-3 text-left ${current?.id === run.id ? 'border-[#9af7bd]/25 bg-[#9af7bd]/[.06]' : 'border-white/[.08] bg-[#07110f]'}`}><p className="font-mono text-[11px]">{run.id}</p><p className="mt-1 text-xs text-[#82998f]">{run.summary || run.status}</p></button>) : <EmptyState text="No investigations recorded yet." />}</div>
                <div className="max-h-[620px] space-y-3 overflow-y-auto rounded-2xl border border-white/[.08] bg-[#07110f] p-4">{current?.events.length ? current.events.map((item) => <div key={item.id} className="border-b border-white/[.06] pb-3"><div className="flex justify-between gap-3"><p className="font-mono text-[10px] text-[#8ea39a]">{item.event_type}</p><time className="text-[10px] text-[#496158]">{new Date(item.created_at).toLocaleTimeString()}</time></div><p className="mt-1 text-xs leading-5 text-[#82998f]">{item.message}</p></div>) : <EmptyState text="Select a run to inspect its audit events." />}</div>
              </div>
            </section>
          )}

          {workspaceView === 'investigation' && <>
          <section className="mt-5 rounded-[24px] border border-white/10 bg-[#0a1714] p-5">
            <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold">Investigation loop</h2>
                  {current && <Badge tone={statusTone(current.status)}>{current.status.replaceAll('_', ' ')}</Badge>}
                  {current?.degraded_mode && <Badge tone="amber">Degraded mode</Badge>}
                </div>
                <p className="mt-1 font-mono text-[11px] text-[#5f786e]">{current?.id ?? 'No investigation selected'}</p>
              </div>
              {current?.status === 'HUMAN_REVIEW' && <button onClick={acknowledgeReview} className="rounded-lg border border-[#ffcf7a]/25 px-3 py-2 text-xs font-semibold text-[#ffd48b]">Acknowledge human review</button>}
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 md:grid-cols-5">
              {pipeline.map((stage, index) => {
                const active = Boolean(current) || (loading && index < 2);
                return (
                  <div key={stage} className={`relative rounded-xl border px-3 py-3 ${active ? 'border-[#9af7bd]/20 bg-[#9af7bd]/[.055]' : 'border-white/[.07] bg-white/[.02]'}`}>
                    <div className="flex items-center gap-2">
                      <span className={`grid h-6 w-6 place-items-center rounded-md text-[10px] font-bold ${active ? 'bg-[#9af7bd] text-[#07110f]' : 'bg-white/[.05] text-[#5f786e]'}`}>{index + 1}</span>
                      <span className={`text-xs font-semibold ${active ? 'text-[#dbe8e2]' : 'text-[#60786e]'}`}>{stage}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,.8fr)]">
            <div className="min-w-0 rounded-[24px] border border-white/10 bg-[#0a1714]">
              <div className="flex gap-1 overflow-x-auto border-b border-white/10 p-2">
                {(['hypotheses', 'evidence', 'audit'] as const).map((tab) => (
                  <button key={tab} onClick={() => setActiveTab(tab)} className={`rounded-lg px-4 py-2 text-xs font-semibold capitalize ${activeTab === tab ? 'bg-white/[.08] text-white' : 'text-[#71877e] hover:text-[#aebfb8]'}`}>{tab}</button>
                ))}
              </div>
              <div className="max-h-[620px] space-y-3 overflow-y-auto p-4 sm:p-5">
                {activeTab === 'hypotheses' && (current?.hypotheses.length ? current.hypotheses.map((item) => (
                  <article key={item.id} className="rounded-2xl border border-white/[.08] bg-[#07110f] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={statusTone(item.status)}>{item.status.replaceAll('_', ' ')}</Badge>
                          <span className="font-mono text-[10px] text-[#567066]">{item.id}</span>
                        </div>
                        <h3 className="mt-3 font-semibold text-[#e2ece7]">{item.title}</h3>
                        <p className="mt-1 text-xs leading-5 text-[#82998f]">{item.description}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xl font-semibold">{Math.round(item.confidence * 100)}%</p>
                        <p className="text-[9px] uppercase tracking-[.12em] text-[#567066]">confidence</p>
                      </div>
                    </div>
                    <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/[.06]"><div className="h-full rounded-full bg-[#9af7bd]" style={{ width: `${item.confidence * 100}%` }} /></div>
                    {item.critic_decision && (
                      <div className="mt-4 border-l-2 border-[#8bc5ff]/50 pl-3">
                        <p className="text-[10px] font-bold uppercase tracking-[.12em] text-[#8bc5ff]">Critic: {item.critic_decision.decision.replaceAll('_', ' ')}</p>
                        <p className="mt-1 text-xs leading-5 text-[#8da098]">{item.critic_decision.reason}</p>
                      </div>
                    )}
                  </article>
                )) : <EmptyState text={loading ? 'The Investigator is forming structured hypotheses…' : 'Run an investigation to see hypothesis and critic decisions.'} />)}

                {activeTab === 'evidence' && (current?.evidence.length ? current.evidence.map((item) => (
                  <article key={item.id} className="rounded-2xl border border-white/[.08] bg-[#07110f] p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={item.kind.includes('FAILED') || item.kind.includes('TIMEOUT') ? 'amber' : 'neutral'}>{item.kind.replaceAll('_', ' ')}</Badge>
                      <span className="font-mono text-[10px] text-[#567066]">{item.source}</span>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-[#b8c8c1]">{item.observation}</p>
                  </article>
                )) : <EmptyState text="Normalized tool evidence will appear here." />)}

                {activeTab === 'audit' && (current?.events.length ? current.events.map((item) => (
                  <div key={item.id} className="grid grid-cols-[10px_minmax(0,1fr)] gap-3">
                    <div className="pt-1"><span className="block h-2 w-2 rounded-full bg-[#597168]" /></div>
                    <div className="border-b border-white/[.06] pb-3">
                      <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-mono text-[10px] text-[#8ea39a]">{item.event_type}</p><time className="text-[10px] text-[#496158]">{new Date(item.created_at).toLocaleTimeString()}</time></div>
                      <p className="mt-1 text-xs leading-5 text-[#71877e]">{item.message}</p>
                    </div>
                  </div>
                )) : <EmptyState text="Every state change, model call, policy decision, and failure is auditable." />)}
              </div>
            </div>

            <aside className="rounded-[24px] border border-white/10 bg-[#0a1714] p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Final assessment</h2>
                {current && <span className="font-mono text-[10px] text-[#567066]">${current.estimated_cost_usd.toFixed(4)}</span>}
              </div>
              <p className="mt-1 text-xs leading-5 text-[#71877e]">Observed facts stay separate from hypotheses and validated findings.</p>
              <div className="mt-5 space-y-3">
                {current?.findings.length ? current.findings.map((item) => (
                  <article key={item.id} className={`rounded-2xl border p-4 ${item.status === 'VALIDATED' ? 'border-[#9af7bd]/20 bg-[#9af7bd]/[.045]' : 'border-[#ffcf7a]/20 bg-[#ffcf7a]/[.04]'}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Badge tone={statusTone(item.status)}>{item.status.replaceAll('_', ' ')}</Badge>
                      <span className="text-xs font-semibold text-[#9eb0a8]">{Math.round(item.confidence * 100)}%</span>
                    </div>
                    <h3 className="mt-3 text-sm font-semibold leading-5">{item.title}</h3>
                    <p className="mt-2 text-xs leading-5 text-[#82998f]">{item.recommendation}</p>
                    <p className="mt-3 text-[10px] uppercase tracking-[.1em] text-[#526a61]">{item.evidence_refs.length} evidence reference{item.evidence_refs.length === 1 ? '' : 's'}</p>
                  </article>
                )) : <EmptyState text="No findings have been declared. Evidence is required before conclusion." />}
              </div>
            </aside>
          </section>
          </>}
        </div>
      </div>
    </main>
  );
}
