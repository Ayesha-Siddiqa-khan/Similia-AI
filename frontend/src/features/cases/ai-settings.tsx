"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, KeyRound, ShieldCheck } from "lucide-react";
import { Badge, Loading, Notice, Panel } from "@/components/ui";
import { del, post, put, useAiSettings } from "./api";
import type { AiSettings } from "./types";

const when = (iso: string | null) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";

export function AiSettingsPage() {
  const client = useQueryClient();
  const query = useAiSettings();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [activeFor, setActiveFor] = useState("1d");
  const [renewFor, setRenewFor] = useState("1d");
  const [show, setShow] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const done = (data: AiSettings) => { client.setQueryData(["ai-settings"], data); setApiKey(""); setShow(false); setConfirmRemove(false); };
  const save = useMutation({
    mutationFn: (settings: AiSettings) => put<AiSettings>("settings/ai", { model: model ?? settings.model, ...(apiKey.trim() ? { api_key: apiKey.trim(), active_for: activeFor } : {}) }),
    onSuccess: done,
  });
  const activate = useMutation({ mutationFn: () => post<AiSettings>("settings/ai/activate", { active_for: renewFor }), onSuccess: done });
  const pause = useMutation({ mutationFn: () => post<AiSettings>("settings/ai/deactivate"), onSuccess: done });
  const remove = useMutation({ mutationFn: () => del<AiSettings>("settings/ai"), onSuccess: (data) => { done(data); setModel(null); } });

  if (query.isPending) return <Loading />;
  if (query.isError) return <Notice error>{query.error.message}</Notice>;
  const settings = query.data;
  const chosenModel = model ?? settings.model;
  const editable = settings.vault_ready;
  const canSave = editable && (apiKey.trim().length > 0 || (settings.configured && chosenModel !== settings.model));
  const status = !settings.configured ? { tone: "warn" as const, text: "No key yet" } : settings.active ? { tone: "good" as const, text: "Active" } : { tone: "warn" as const, text: "Paused" };
  const periods = settings.active_options;

  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">YOUR ACCOUNT</span><h1>AI Settings</h1><p>Use your own AI key. AI features in your workspace run on your account, and only while the key is active.</p></div>
        <Badge tone={status.tone}>{status.text}</Badge></div>
      {!settings.vault_ready && <Notice error>Secure key storage is not set up on this server yet, so keys cannot be saved. Ask your administrator to set <code>APP_ENCRYPTION_KEY</code>.</Notice>}

      <Panel title="Your Anthropic API key" description={settings.configured ? `Saved key ending in ${settings.key_last4}${settings.validated_at ? ` · verified ${new Date(settings.validated_at).toLocaleDateString()}` : ""}` : "Paste a key to turn on AI follow-up questions and case analysis."}>
        <form className="case-form" onSubmit={(e) => { e.preventDefault(); save.mutate(settings); }} autoComplete="off">
          <div className="field">
            <label htmlFor="ai-key">{settings.configured ? "Replace key (leave empty to keep the current one)" : "API key"}</label>
            <div className="password-field">
              <input id="ai-key" type={show ? "text" : "password"} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-ant-…" autoComplete="off" spellCheck={false} data-1p-ignore data-lpignore="true" disabled={!editable} />
              <button type="button" className="password-toggle" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide key" : "Show key"} aria-pressed={show}>{show ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}</button>
            </div>
          </div>
          <div className="symptom-grid">
            <div className="field"><label htmlFor="ai-model">Model</label>
              <select id="ai-model" value={chosenModel} onChange={(e) => setModel(e.target.value)} disabled={!editable}>{settings.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></div>
            <div className="field"><label htmlFor="ai-active-for">Keep the key active for</label>
              <select id="ai-active-for" value={activeFor} onChange={(e) => setActiveFor(e.target.value)} disabled={!editable}>{periods.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</select></div>
          </div>
          <p className="fine-print">After this period the key stays saved but is paused. You turn it on again with one click, without pasting it again.</p>
          {save.isError && <Notice error>{save.error.message}</Notice>}
          {save.isSuccess && <Notice>Saved. Your key was checked with Anthropic and is stored encrypted. It is never shown again.</Notice>}
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

      {settings.usage && (
        <Panel title="Your usage this hour" description="Limits protect you from unexpected costs on your own key">
          <dl className="measurements">
            <div><dt>Question requests</dt><dd>{settings.usage.questions.used} of {settings.usage.questions.limit}</dd></div>
            <div><dt>Case analyses</dt><dd>{settings.usage.analyses.used} of {settings.usage.analyses.limit}</dd></div>
          </dl>
        </Panel>
      )}

      <Panel title="How to get a key" description="Takes about two minutes">
        <ol className="panel-padding help-steps">
          <li>Sign in at console.anthropic.com and add billing.</li>
          <li>Open <strong>API Keys</strong> and choose <strong>Create key</strong>. Give it a name such as &ldquo;Similia&rdquo;.</li>
          <li>Set a <strong>monthly spend limit</strong> for that key or workspace so costs stay predictable.</li>
          <li>Copy the key once (it starts with <code>sk-ant-</code>) and paste it above.</li>
        </ol>
      </Panel>

      <Panel title="Privacy and cost" description="What happens to your key and your cases">
        <ul className="panel-padding help-steps">
          <li><ShieldCheck size={14} aria-hidden /> Your key is encrypted before it is stored and is never sent back to your browser. Only its last four characters are shown.</li>
          <li>The key works only while it is active. After the period you chose it is paused automatically, which limits the damage if a session is left open.</li>
          <li>Each AI request uses your key and is billed by Anthropic to your account. A short list of questions costs very little; a full analysis costs more.</li>
          <li>Case text you analyse is sent to Anthropic under your account&apos;s terms. Only analyse patients who have consented.</li>
          <li>Searching the book library uses this app&apos;s own search service, not your key.</li>
          <li>Anyone with your key can spend your money. Never share it, and remove it here if you think it leaked, then delete it in the Anthropic console too.</li>
        </ul>
      </Panel>
    </>
  );
}
