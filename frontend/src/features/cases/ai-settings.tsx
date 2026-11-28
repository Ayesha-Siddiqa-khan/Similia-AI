"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, KeyRound, ShieldCheck } from "lucide-react";
import { Badge, Loading, Notice, Panel } from "@/components/ui";
import { ProgressDots } from "@/components/progress-dots";
import { api } from "@/lib/backend";
import { del, post, put, useAiSettings } from "./api";
import type { AiModelOption, AiSettings } from "./types";

const when = (iso: string | null) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";

interface ConnectionCheck {
  service: string;
  model: string | null;
  status: "passed" | "failed" | "skipped";
  detail: string;
  upstream_status: number | null;
}

const limitFields = [
  { field: "hourly_analysis_limit", label: "Hourly", window: "hourly" },
  { field: "daily_analysis_limit", label: "Daily", window: "daily" },
] as const;
type LimitField = typeof limitFields[number]["field"];

export function AiSettingsPage() {
  const client = useQueryClient();
  const query = useAiSettings();
  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [activeFor, setActiveFor] = useState("1d");
  const [renewFor, setRenewFor] = useState("1d");
  const [show, setShow] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [limits, setLimits] = useState<Partial<Record<LimitField, string>>>({});
  const [catalog, setCatalog] = useState<{ models: AiModelOption[] } | { error: string } | null>(null);
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const done = (data: AiSettings) => { client.setQueryData(["ai-settings"], data); setApiKey(""); setShow(false); setConfirmRemove(false); };
  const save = useMutation({
    mutationFn: (selection: { provider: string; model: string }) => put<AiSettings>("settings/ai", { ...selection, ...(apiKey.trim() ? { api_key: apiKey.trim(), active_for: activeFor } : {}) }),
    onSuccess: (data) => { done(data); setProvider(null); setModel(null); setCatalog(null); },
  });
  const activate = useMutation({ mutationFn: () => post<AiSettings>("settings/ai/activate", { active_for: renewFor }), onSuccess: done });
  const pause = useMutation({ mutationFn: () => post<AiSettings>("settings/ai/deactivate"), onSuccess: done });
  const remove = useMutation({ mutationFn: () => del<AiSettings>("settings/ai"), onSuccess: (data) => { done(data); setProvider(null); setModel(null); setCatalog(null); } });
  const saveLimit = useMutation({
    mutationFn: ({ field, limit }: { field: LimitField; limit: number | null }) =>
      put<AiSettings>("settings/ai/analysis-limit", { [field]: limit }),
    onSuccess: (data, { field }) => {
      client.setQueryData(["ai-settings"], data);
      setLimits((previous) => ({ ...previous, [field]: undefined }));
    },
  });
  const diagnose = useMutation({
    mutationFn: () => post<ConnectionCheck[]>("settings/ai/diagnostics"),
    onSettled: () => { void client.invalidateQueries({ queryKey: ["ai-settings"] }); },
  });

  const settings = query.data;
  const chosenProvider = provider ?? settings?.provider ?? "anthropic";
  const switching = chosenProvider !== settings?.provider;
  const requestKey = apiKey.trim();
  const canLoadModels = Boolean(settings?.vault_ready) && (requestKey.length >= 20 || (!requestKey && settings?.configured && !switching));
  useEffect(() => {
    if (!canLoadModels) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void api<AiModelOption[]>("settings/ai/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: chosenProvider, ...(requestKey ? { api_key: requestKey } : {}) }),
        signal: controller.signal,
      }).then((models) => {
        if (!controller.signal.aborted) setCatalog(Array.isArray(models) ? { models } : { error: "The model list could not be loaded." });
      }, (error: Error) => {
        if (!controller.signal.aborted) setCatalog({ error: error.message });
      });
    }, 450);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [canLoadModels, catalogAttempt, chosenProvider, requestKey]);

  if (query.isPending) return <Loading />;
  if (query.isError || !settings) return <Notice error>{query.error?.message ?? "AI settings are unavailable."}</Notice>;
  const anthropic = chosenProvider === "anthropic";
  const liveModels = catalog && "models" in catalog ? catalog.models : undefined;
  const listedModels = liveModels ?? (anthropic ? settings.models : []);
  const requestedModel = model ?? (!switching ? settings.model : "");
  const listedSelection = listedModels.some((option) => option.id === requestedModel);
  const savedSelection = settings.configured && !switching && !requestKey && requestedModel === settings.model;
  const chosenModel = listedSelection || savedSelection ? requestedModel : "";
  const editable = settings.vault_ready;
  const canSave = editable && Boolean(chosenModel) && (requestKey.length > 0 || (!switching && settings.configured && chosenModel !== settings.model));
  const savedProvider = settings.providers.find((option) => option.id === settings.provider)?.label ?? settings.provider;
  const status = !settings.configured ? { tone: "warn" as const, text: "No key yet" } : settings.active ? { tone: "good" as const, text: "Enabled in Similia" } : { tone: "warn" as const, text: "Paused" };
  const periods = settings.active_options;

  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">YOUR ACCOUNT</span><h1>AI Settings</h1><p>Use your own AI key. AI features in your workspace run on your account, and only while the key is active.</p></div>
        <Badge tone={status.tone}>{status.text}</Badge></div>
      {!settings.vault_ready && <Notice error>Secure key storage is not set up on this server yet, so keys cannot be saved. Ask your administrator to set <code>APP_ENCRYPTION_KEY</code>.</Notice>}

      <Panel title="Your AI provider" description={settings.configured ? `${savedProvider} key ending in ${settings.key_last4}${settings.validated_at ? ` · checked ${new Date(settings.validated_at).toLocaleDateString()}` : ""}` : "Choose a provider for case analysis, follow-up questions and report translation."}>
        <form className="case-form" onSubmit={(e) => { e.preventDefault(); if (canSave && !save.isPending) save.mutate({ provider: chosenProvider, model: chosenModel }); }} autoComplete="off">
          <div className="field">
            <label htmlFor="ai-provider">Provider</label>
            <select id="ai-provider" value={chosenProvider} onChange={(e) => { setProvider(e.target.value); setModel(null); setApiKey(""); setCatalog(null); setShow(false); save.reset(); }} disabled={!editable || save.isPending}>
              {settings.providers.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
            {settings.configured && switching && <small>Saving a key for this provider replaces your saved {savedProvider} key.</small>}
          </div>
          <div className="field">
            <label htmlFor="ai-key">{settings.configured && !switching ? "Replace key (leave empty to keep the current one)" : "API key"}</label>
            <div className="password-field">
              <input id="ai-key" type={show ? "text" : "password"} value={apiKey} onChange={(e) => { if (e.target.value.trim() !== requestKey) setCatalog(null); setApiKey(e.target.value); }} placeholder={anthropic ? "sk-ant-…" : undefined} autoComplete="off" spellCheck={false} data-1p-ignore data-lpignore="true" disabled={!editable || save.isPending} />
              <button type="button" className="password-toggle" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide key" : "Show key"} aria-pressed={show}>{show ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}</button>
            </div>
          </div>
          <div className="symptom-grid">
            <div className="field"><label htmlFor="ai-model">Model</label>
              <select id="ai-model" value={chosenModel} onChange={(e) => setModel(e.target.value)} disabled={!editable || save.isPending || !listedModels.length}>
                <option value="" disabled>Choose a model</option>
                {savedSelection && !listedSelection && <option value={settings.model}>{settings.model} (saved)</option>}
                {listedModels.map((m) => <option key={m.id} value={m.id}>{m.label === m.id ? m.id : `${m.label} (${m.id})`}</option>)}
              </select>
              {!canLoadModels && !anthropic && <small>Enter the provider API key to load its models.</small>}
              {canLoadModels && !catalog && <small role="status">Loading models…</small>}
              {liveModels?.length === 0 && <small>No compatible chat models were returned.</small>}
              {catalog && "error" in catalog && <><small role="alert">{catalog.error}</small><button type="button" className="text-link" onClick={() => { setCatalog(null); setCatalogAttempt((attempt) => attempt + 1); }}>Retry loading models</button></>}
            </div>
            <div className="field"><label htmlFor="ai-active-for">Keep the key active for</label>
              <select id="ai-active-for" value={activeFor} onChange={(e) => setActiveFor(e.target.value)} disabled={!editable}>{periods.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</select></div>
          </div>
          <p className="fine-print">After this period the key stays saved but is paused. You turn it on again with one click, without pasting it again.</p>
          {save.isError && <Notice error>{save.error.message}</Notice>}
          {save.isSuccess && <Notice>AI settings saved. Your API key is stored encrypted.</Notice>}
          <div className="button-row">
            <button className="button primary" disabled={!canSave || save.isPending}><KeyRound size={16} />{save.isPending ? "Checking key…" : apiKey.trim() ? "Save and verify" : "Update model"}</button>
            {settings.configured && (confirmRemove
              ? <><button type="button" className="button secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>{remove.isPending ? "Removing…" : "Yes, remove my key"}</button><button type="button" className="button secondary" onClick={() => setConfirmRemove(false)}>Cancel</button></>
              : <button type="button" className="button secondary" onClick={() => setConfirmRemove(true)}>Remove key</button>)}
          </div>
          {remove.isError && <Notice error>{remove.error.message}</Notice>}
        </form>
      </Panel>

      {settings.configured && (
        <Panel title="Key status" description={settings.active ? `Active until ${when(settings.active_until)}` : "Paused. AI features are off until you turn the key on."}>
          <div className="case-form">
            {settings.active && <p className="fine-print">This timer enables the key in Similia. {savedProvider} checks API billing and available credits when you run an analysis.</p>}
            {!settings.active && <Notice>Your key is saved but not active, so AI follow-up questions and analysis are unavailable.</Notice>}
            <div className="symptom-grid">
              <div className="field"><label htmlFor="ai-renew">{settings.active ? "Restart the timer for" : "Turn on for"}</label>
                <select id="ai-renew" value={renewFor} onChange={(e) => setRenewFor(e.target.value)} disabled={!editable}>{periods.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</select></div>
            </div>
            {(activate.isError || pause.isError) && <Notice error>{(activate.error ?? pause.error)?.message}</Notice>}
            <div className="button-row">
              <button type="button" className="button primary" disabled={!editable || activate.isPending} onClick={() => activate.mutate()}>{activate.isPending ? "Working…" : settings.active ? "Restart timer" : "Turn on"}</button>
              {settings.active && <button type="button" className="button secondary" disabled={!editable || pause.isPending} onClick={() => pause.mutate()}>{pause.isPending ? "Pausing…" : "Pause now"}</button>}
            </div>
          </div>
        </Panel>
      )}

      <Panel title="Connection diagnostics" description="Tests your saved AI model, Voyage and semantic library search using fixed sample text. These checks may use API quota.">
        <div className="case-form">
          <div className="button-row"><button className="button secondary" disabled={diagnose.isPending} aria-busy={diagnose.isPending} onClick={() => diagnose.mutate()}>{diagnose.isPending ? <>Checking connections <ProgressDots /></> : "Run connection checks"}</button></div>
          {diagnose.isError && <Notice error>{diagnose.error.message}</Notice>}
          {diagnose.data && <dl className="measurements" aria-live="polite">
            {diagnose.data.map((check) => <div key={check.service}>
              <dt>{check.service}{check.model && <> · {check.model}</>}</dt>
              <dd><Badge tone={check.status === "passed" ? "good" : check.status === "failed" ? "bad" : "neutral"}>{check.status}</Badge> {check.detail}{check.upstream_status != null && <> (HTTP {check.upstream_status})</>}</dd>
            </div>)}
          </dl>}
        </div>
      </Panel>

      {settings.usage && (
        <Panel title="AI usage and limits" description="Limits protect you from unexpected costs on your own key">
          <dl className="measurements">
            <div><dt>Question requests in the past hour</dt><dd>{settings.usage.questions.used} of {settings.usage.questions.limit}</dd></div>
            <div><dt>Case analyses in the past hour</dt><dd>{settings.usage.analyses.used}{settings.usage.analyses.limit > 0 ? ` of ${settings.usage.analyses.limit}` : " · No hourly cap"}</dd></div>
            {settings.usage.daily_analyses && <div><dt>Case analyses in the past 24 hours</dt><dd>{settings.usage.daily_analyses.used}{settings.usage.daily_analyses.limit > 0 ? ` of ${settings.usage.daily_analyses.limit}` : " · No daily cap"}</dd></div>}
          </dl>
          {settings.configured && limitFields.map(({ field, label, window }) => {
            const input = limits[field] ?? String(settings[field] ?? "");
            const limit = input === "" ? null : Number(input);
            const savingThis = saveLimit.variables?.field === field;
            const disabled = saveLimit.isPending || limit === (settings[field] ?? null);
            return <form key={field} className="case-form" onSubmit={(event) => {
              event.preventDefault();
              if (!disabled) saveLimit.mutate({ field, limit });
            }}>
              <div className="field">
                <label htmlFor={field}>{label} case analysis limit</label>
                <input id={field} type="number" min={0} max={2147483647} step={1} value={input} disabled={saveLimit.isPending} onChange={(event) => {
                  setLimits({ ...limits, [field]: event.target.value });
                  if (savingThis) saveLimit.reset();
                }} />
                <small>Enter 0 for no {window} cap. Leave blank to use the workspace default.{window === "daily" ? " Applies over a rolling 24-hour window." : ""}</small>
              </div>
              {savingThis && saveLimit.isError && <Notice error>{saveLimit.error.message}</Notice>}
              {savingThis && saveLimit.isSuccess && <Notice>{label} limit saved.</Notice>}
              <div className="button-row"><button className="button secondary" disabled={disabled}>{saveLimit.isPending && savingThis ? "Saving…" : `Save ${window} limit`}</button></div>
            </form>;
          })}
        </Panel>
      )}

      <Panel title="How to get a key">
        <ol className="panel-padding help-steps">
          <li>Create an API key in your chosen provider&apos;s developer console and check API billing.</li>
          <li>Select that provider here, paste the key, and choose or enter your chat model.</li>
          <li>Use OpenRouter to select additional models by their OpenRouter model ID and API key.</li>
        </ol>
      </Panel>

      <Panel title="Privacy and cost" description="What happens to your key and your cases">
        <ul className="panel-padding help-steps">
          <li><ShieldCheck size={14} aria-hidden /> Your key is encrypted before it is stored and is never sent back to your browser. Only its last four characters are shown.</li>
          <li>The key works only while it is active. After the period you chose it is paused automatically, which limits the damage if a session is left open.</li>
          <li>AI requests are billed to your account by your selected provider.</li>
          <li>Case text is sent to the selected provider and, for OpenRouter, its model host. Only analyse patients who have consented to that processing.</li>
          <li>Searching the book library uses this app&apos;s own search service, not your key.</li>
          <li>If a key leaks, remove it here and revoke it in the provider&apos;s console.</li>
        </ul>
      </Panel>
    </>
  );
}
