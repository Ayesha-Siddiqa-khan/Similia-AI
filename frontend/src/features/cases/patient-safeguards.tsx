"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch, type UseFormRegisterReturn } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { Download, Trash2 } from "lucide-react";
import { Badge, Empty, Loading, Notice, Panel } from "@/components/ui";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { api } from "@/lib/backend";
import { del, patch, post, usePatientConsents, usePatientHistory } from "./api";
import { guardianPayload, isMinorAge, personalShape, requireGuardianForMinors } from "./guardian";
import { casePath, formatDate, statusLabel, statusTone } from "./paths";
import type { Patient } from "./types";

/** Refresh everything that shows this patient after a change. */
export function refreshPatient(client: QueryClient, id: string) {
  void client.invalidateQueries({ queryKey: ["patients"] });
  for (const key of ["patient", "consents", "history"]) void client.invalidateQueries({ queryKey: [key, id] });
}

export function GuardianFields({ name, relationship, nameError, relationshipError, idPrefix }: { name: UseFormRegisterReturn; relationship: UseFormRegisterReturn; nameError?: string; relationshipError?: string; idPrefix: string }) {
  return (
    <>
      <p className="fine-print">Patients under 18 need a guardian. Record who gave consent on the patient&apos;s behalf.</p>
      <div className="field"><label htmlFor={`${idPrefix}-gname`}>Guardian name</label><input id={`${idPrefix}-gname`} autoComplete="off" maxLength={200} {...name} aria-invalid={!!nameError} />{nameError && <p className="field-error" role="alert">{nameError}</p>}</div>
      <div className="field"><label htmlFor={`${idPrefix}-grel`}>Relationship to patient</label><input id={`${idPrefix}-grel`} autoComplete="off" maxLength={100} {...relationship} aria-invalid={!!relationshipError} />{relationshipError && <p className="field-error" role="alert">{relationshipError}</p>}</div>
    </>
  );
}

const editSchema = z.object(personalShape).superRefine(requireGuardianForMinors);
type EditFields = z.infer<typeof editSchema>;

function EditDetails({ patient }: { patient: Patient }) {
  const client = useQueryClient();
  const archived = !!patient.archived_at;
  const { register, handleSubmit, control, formState: { errors } } = useForm<EditFields>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      full_name: patient.full_name, age_years: patient.age_years, date_of_birth: patient.date_of_birth ?? "", sex: patient.sex, preferred_language: patient.preferred_language,
      contact: patient.contact ?? "", notes: patient.notes ?? "", guardian_name: patient.guardian_name ?? "", guardian_relationship: patient.guardian_relationship ?? "",
    },
  });
  const [age, dob] = useWatch({ control, name: ["age_years", "date_of_birth"] });
  const minor = isMinorAge(age, dob);
  const save = useMutation({
    mutationFn: (v: EditFields) => patch<Patient>(`patients/${patient.id}`, { full_name: v.full_name, age_years: v.age_years, sex: v.sex, preferred_language: v.preferred_language, contact: v.contact || null, notes: v.notes || null, ...guardianPayload(v) }),
    onSuccess: () => refreshPatient(client, patient.id),
  });
  return (
    <Panel title="Edit details" description="Changes are saved to the patient record.">
      {archived && <Notice>This patient is archived (read-only). Record consent again to reopen the record.</Notice>}
      <form className="case-form" onSubmit={handleSubmit((v) => save.mutate(v))} noValidate>
        <fieldset disabled={archived || save.isPending} className="panel-stack">
          <div className="symptom-grid">
            <div className="field"><label htmlFor="e-name">Full name</label><input id="e-name" autoComplete="off" maxLength={200} {...register("full_name")} aria-invalid={!!errors.full_name} />{errors.full_name && <p className="field-error" role="alert">{errors.full_name.message}</p>}</div>
            <div className="field"><label htmlFor="e-age">Age (years)</label><input id="e-age" type="number" min={0} max={130} {...register("age_years", { setValueAs: (v) => v === "" || v == null ? null : Number(v) })} />{errors.age_years && <p className="field-error" role="alert">{errors.age_years.message}</p>}</div>
            <div className="field"><label htmlFor="e-dob">Date of birth (optional)</label><input id="e-dob" type="date" {...register("date_of_birth")} />{errors.date_of_birth && <p className="field-error" role="alert">{errors.date_of_birth.message}</p>}</div>
            <div className="field"><label htmlFor="e-sex">Sex</label><select id="e-sex" {...register("sex")}><option value="unspecified">Not specified</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option></select></div>
            <div className="field"><label htmlFor="e-lang">Language for case-taking</label><select id="e-lang" {...register("preferred_language")}><option value="en">English</option><option value="hi">Hindi · हिन्दी</option><option value="ur">Urdu · اردو</option></select></div>
            <div className="field"><label htmlFor="e-contact">Contact (optional)</label><input id="e-contact" autoComplete="off" maxLength={200} {...register("contact")} />{errors.contact && <p className="field-error" role="alert">{errors.contact.message}</p>}</div>
          </div>
          {minor && <GuardianFields idPrefix="e" name={register("guardian_name")} relationship={register("guardian_relationship")} nameError={errors.guardian_name?.message} relationshipError={errors.guardian_relationship?.message} />}
          <div className="field"><label htmlFor="e-notes">Notes (optional)</label><textarea id="e-notes" rows={2} maxLength={4000} {...register("notes")} />{errors.notes && <p className="field-error" role="alert">{errors.notes.message}</p>}</div>
        </fieldset>
        {save.isError && <Notice error>{save.error.message}</Notice>}
        {save.isSuccess && <p className="fine-print" role="status">Details saved.</p>}
        <button className="button primary" disabled={archived || save.isPending}>{save.isPending ? "Saving…" : "Save details"}</button>
      </form>
    </Panel>
  );
}

/** Keyed by the last update so the form shows what the server saved. */
export function EditDetailsPanel({ patient }: { patient: Patient }) {
  return <EditDetails key={patient.updated_at} patient={patient} />;
}

export function ConsentPanel({ patient }: { patient: Patient }) {
  const client = useQueryClient();
  const consents = usePatientConsents(patient.id);
  const [confirming, setConfirming] = useState(false);
  const withdraw = useMutation({
    mutationFn: () => post<Patient>(`patients/${patient.id}/consent/withdraw`),
    onSuccess: () => { setConfirming(false); refreshPatient(client, patient.id); },
    onError: () => setConfirming(false),
  });
  const grant = useMutation({
    mutationFn: () => post<Patient>(`patients/${patient.id}/consent`),
    onSuccess: () => refreshPatient(client, patient.id),
  });
  return (
    <Panel title="Consent" description={patient.consent_active ? "Consent is active. AI analysis is allowed for this patient." : "Consent has been withdrawn. AI analysis is blocked and the record is read-only."} action={<Badge tone={patient.consent_active ? "good" : "warn"}>{patient.consent_active ? "Consent active" : "Consent withdrawn"}</Badge>}>
      <div className="panel-padding stack">
        {consents.isPending ? <Loading /> : consents.isError ? <Notice error>{consents.error.message}</Notice> : consents.data.length === 0 ? <p className="fine-print">No consent has been recorded.</p> : (
          <div className="registered-list" aria-label="Consent history">{consents.data.map((c) => <div key={c.id}><span>Granted {formatDate(c.granted_at)}</span><Badge tone={c.withdrawn_at ? "neutral" : "good"}>{c.withdrawn_at ? `Withdrawn ${formatDate(c.withdrawn_at)}` : "Active"}</Badge></div>)}</div>
        )}
        {withdraw.isError && <Notice error>{withdraw.error.message}</Notice>}
        {grant.isError && <Notice error>{grant.error.message}</Notice>}
        {patient.consent_active
          ? <div><button type="button" className="button secondary" onClick={() => setConfirming(true)}>Withdraw consent</button></div>
          : <div><button type="button" className="button primary" disabled={grant.isPending} onClick={() => grant.mutate()}>{grant.isPending ? "Recording…" : "Record consent again"}</button><p className="fine-print">Only record consent after the patient (or guardian) has agreed again.</p></div>}
      </div>
      {confirming && (
        <ConfirmDialog id="withdraw" title="Withdraw consent?" confirmLabel="Withdraw consent" busyLabel="Withdrawing…" busy={withdraw.isPending} danger onCancel={() => setConfirming(false)} onConfirm={() => withdraw.mutate()}>
          <p>This stops all AI use for {patient.full_name} and archives the record, so it becomes read-only. Nothing is deleted. You can record consent again later to reopen it.</p>
        </ConfirmDialog>
      )}
    </Panel>
  );
}

export function HistoryPanel({ patientId }: { patientId: string }) {
  const history = usePatientHistory(patientId);
  return (
    <Panel title="Case history" description="Every case for this patient, newest first. Open a case to see its details.">
      {history.isPending ? <Loading /> : history.isError ? <Notice error>{history.error.message}</Notice> : history.data.length === 0 ? <Empty title="No cases yet">Cases appear here once you start one.</Empty> : (
        <div className="registered-list">{history.data.map((c) => (
          <div key={c.id}>
            <span><strong><Link className="text-link" href={casePath(c.id)}>{c.chief_complaint || "Untitled case"}</Link></strong><br /><small>{formatDate(c.created_at)} · {c.analysis_count} {c.analysis_count === 1 ? "analysis" : "analyses"}{c.signed_at ? <> · {c.review_decision === "rejected" ? "Analysis rejected" : c.chosen_remedy ? `Signed remedy: ${c.chosen_remedy}` : "Signed off"} on {formatDate(c.signed_at)}</> : null}</small></span>
            <Badge tone={statusTone[c.status]}>{statusLabel[c.status]}</Badge>
          </div>
        ))}</div>
      )}
    </Panel>
  );
}

/** Save a JSON document as a file in the browser (no network involved). */
export function saveJsonFile(data: unknown, fileName: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = fileName;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function DownloadRecord({ patient }: { patient: Patient }) {
  const download = useMutation({
    mutationFn: async () => { saveJsonFile(await api<unknown>(`patients/${patient.id}/export`), `patient-${patient.identifier.replace(/[^\w.-]+/g, "_")}.json`); },
  });
  return (
    <>
      <button type="button" className="button secondary" disabled={download.isPending} onClick={() => download.mutate()}><Download size={16} />{download.isPending ? "Preparing…" : "Download patient record"}</button>
      {download.isError && <Notice error>{download.error.message}</Notice>}
    </>
  );
}

export function ErasePanel({ patient }: { patient: Patient }) {
  const router = useRouter();
  const client = useQueryClient();
  const [typed, setTyped] = useState("");
  const erase = useMutation({
    mutationFn: () => del<void>(`patients/${patient.id}?confirm_identifier=${encodeURIComponent(typed)}`),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["patients"] }); void client.invalidateQueries({ queryKey: ["cases"] }); router.push("/workspace/patients"); },
  });
  if (!patient.archived_at) return null;
  const matches = typed === patient.identifier;
  return (
    <section className="panel danger-zone" aria-labelledby="erase-title">
      <div className="panel-heading"><div><h2 id="erase-title">Erase patient</h2><p>Permanent. This deletes the patient, all cases, analyses, reviews and consent records. It cannot be undone.</p></div></div>
      <form className="case-form panel-padding" onSubmit={(e) => { e.preventDefault(); if (matches) erase.mutate(); }}>
        <p>Download the patient record first if you may need a copy. To confirm, type the patient&apos;s ID <strong>{patient.identifier}</strong> exactly.</p>
        <div className="field"><label htmlFor="erase-id">Type the patient ID to confirm</label><input id="erase-id" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} /></div>
        {erase.isError && <Notice error>{erase.error.message}</Notice>}
        <div><button className="button danger" disabled={!matches || erase.isPending}><Trash2 size={16} />{erase.isPending ? "Erasing…" : "Erase patient permanently"}</button></div>
      </form>
    </section>
  );
}
