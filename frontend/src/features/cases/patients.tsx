"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { UserPlus } from "lucide-react";
import { Badge, Empty, Loading, Notice, Panel } from "@/components/ui";
import { post, useCases, usePatient, usePatients } from "./api";
import { guardianPayload, isMinorAge, personalShape, requireGuardianForMinors } from "./guardian";
import { casePath, patientPath, statusLabel, statusTone } from "./paths";
import { ConsentPanel, DownloadRecord, EditDetailsPanel, ErasePanel, GuardianFields, HistoryPanel } from "./patient-safeguards";
import type { Patient } from "./types";

// Limits match the backend (backend/app/schemas/cases.py PatientCreate).
const schema = z.object({
  identifier: z.string().trim().min(1, "Enter a patient ID.").max(64, "Use 64 characters or fewer."),
  ...personalShape,
  consent_given: z.boolean().refine((value) => value, "Record the patient's consent before continuing."),
}).superRefine(requireGuardianForMinors);
type Fields = z.infer<typeof schema>;

function NewPatientForm() {
  const router = useRouter();
  const client = useQueryClient();
  const { register, handleSubmit, control, formState: { errors } } = useForm<Fields>({
    resolver: zodResolver(schema),
    defaultValues: { identifier: "", full_name: "", age_years: null, date_of_birth: "", guardian_name: "", guardian_relationship: "", sex: "unspecified", preferred_language: "en", contact: "", notes: "", consent_given: false },
  });
  const [age, dob] = useWatch({ control, name: ["age_years", "date_of_birth"] });
  const minor = isMinorAge(age, dob);
  const create = useMutation({
    mutationFn: (v: Fields) => post<Patient>("patients", {
      identifier: v.identifier, full_name: v.full_name, age_years: v.age_years, sex: v.sex, preferred_language: v.preferred_language,
      contact: v.contact || null, notes: v.notes || null, consent_given: v.consent_given, ...guardianPayload(v),
    }),
    onSuccess: (patient) => { void client.invalidateQueries({ queryKey: ["patients"] }); router.push(patientPath(patient.id)); },
  });
  return (
    <form className="case-form" onSubmit={handleSubmit((v) => create.mutate(v))} noValidate>
      <div className="symptom-grid">
        <div className="field"><label htmlFor="p-id">Patient ID</label><input id="p-id" autoComplete="off" maxLength={64} {...register("identifier")} aria-invalid={!!errors.identifier} />{errors.identifier && <p className="field-error" role="alert">{errors.identifier.message}</p>}</div>
        <div className="field"><label htmlFor="p-name">Full name</label><input id="p-name" autoComplete="off" maxLength={200} {...register("full_name")} aria-invalid={!!errors.full_name} />{errors.full_name && <p className="field-error" role="alert">{errors.full_name.message}</p>}</div>
        <div className="field"><label htmlFor="p-age">Age (years)</label><input id="p-age" type="number" min={0} max={130} {...register("age_years", { setValueAs: (v) => v === "" || v == null ? null : Number(v) })} />{errors.age_years && <p className="field-error" role="alert">{errors.age_years.message}</p>}</div>
        <div className="field"><label htmlFor="p-dob">Date of birth (optional)</label><input id="p-dob" type="date" {...register("date_of_birth")} />{errors.date_of_birth && <p className="field-error" role="alert">{errors.date_of_birth.message}</p>}</div>
        <div className="field"><label htmlFor="p-sex">Sex</label><select id="p-sex" {...register("sex")}><option value="unspecified">Not specified</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option></select></div>
        <div className="field"><label htmlFor="p-lang">Language for case-taking</label><select id="p-lang" {...register("preferred_language")}><option value="en">English</option><option value="hi">Hindi · हिन्दी</option><option value="ur">Urdu · اردو</option></select></div>
        <div className="field"><label htmlFor="p-contact">Contact (optional)</label><input id="p-contact" autoComplete="off" maxLength={200} {...register("contact")} aria-invalid={!!errors.contact} />{errors.contact && <p className="field-error" role="alert">{errors.contact.message}</p>}</div>
      </div>
      {minor && <GuardianFields idPrefix="p" name={register("guardian_name")} relationship={register("guardian_relationship")} nameError={errors.guardian_name?.message} relationshipError={errors.guardian_relationship?.message} />}
      <div className="field"><label htmlFor="p-notes">Notes (optional)</label><textarea id="p-notes" rows={2} maxLength={4000} {...register("notes")} aria-invalid={!!errors.notes} />{errors.notes && <p className="field-error" role="alert">{errors.notes.message}</p>}</div>
      <div className="field consent-field">
        <label htmlFor="p-consent" className="check-label"><input id="p-consent" type="checkbox" {...register("consent_given")} /> The patient (or guardian) has given informed consent to record their health information and to have it analysed with AI decision support. They can withdraw consent at any time.</label>
        {errors.consent_given && <p className="field-error" role="alert">{errors.consent_given.message}</p>}
      </div>
      {create.isError && <Notice error>{create.error.message}</Notice>}
      <button className="button primary" disabled={create.isPending}><UserPlus size={16} />{create.isPending ? "Saving…" : "Create patient"}</button>
    </form>
  );
}

export function PatientsPage() {
  const [adding, setAdding] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const query = usePatients();
  const all = query.data ?? [];
  const archivedCount = all.filter((p) => p.archived_at).length;
  const rows = showArchived ? all : all.filter((p) => !p.archived_at);
  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">PATIENT WORKSPACE</span><h1>Patients</h1><p>Your patients and their cases. Only you can see these records.</p></div><button className="button primary" onClick={() => setAdding((v) => !v)} aria-expanded={adding}><UserPlus size={16} />{adding ? "Close form" : "New patient"}</button></div>
      {adding && <Panel title="New patient" description="Consent is recorded with the patient and checked before any AI analysis."><NewPatientForm /></Panel>}
      {query.isPending ? <Loading /> : query.isError ? <Notice error>{query.error.message}</Notice> : rows.length === 0 && archivedCount === 0 ? <Empty title="No patients yet">Create your first patient to start taking a case.</Empty> : (
        <Panel title="All patients" description={`${rows.length} ${showArchived ? "shown" : "active"}`} action={<label htmlFor="show-archived" className="check-label inline"><input id="show-archived" type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived{archivedCount > 0 ? ` (${archivedCount})` : ""}</label>}>
          <div className="table-scroll"><table><thead><tr><th>Patient</th><th>ID</th><th>Age</th><th>Language</th><th /></tr></thead><tbody>
            {rows.map((p) => <tr key={p.id}><td><strong>{p.full_name}</strong> {p.is_minor && <Badge>Child</Badge>} {!p.consent_active && <Badge tone="warn">Consent withdrawn</Badge>} {p.archived_at && <Badge>Archived</Badge>}</td><td>{p.identifier}</td><td>{p.age_years ?? "—"}</td><td>{p.preferred_language.toUpperCase()}</td><td><Link className="text-link" href={patientPath(p.id)}>Open</Link></td></tr>)}
          </tbody></table></div>
        </Panel>
      )}
    </>
  );
}

export function PatientDetail({ id }: { id: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const patient = usePatient(id);
  const start = useMutation({
    mutationFn: () => post<{ id: string }>("cases", { patient_id: id, language: patient.data?.preferred_language ?? "en" }),
    onSuccess: (created) => { void client.invalidateQueries({ queryKey: ["cases"] }); router.push(casePath(created.id)); },
  });
  if (patient.isPending) return <Loading />;
  if (patient.isError) return <><Notice error>{patient.error.message}</Notice><Link className="button secondary" href="/workspace/patients">Back to patients</Link></>;
  const p = patient.data;
  const archived = !!p.archived_at;
  const blocked = archived ? "This patient is archived (read-only). Record consent again to start a new case." : !p.consent_active ? "Consent has been withdrawn. Record consent again to start a new case." : "";
  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">PATIENT</span><h1>{p.full_name} {p.is_minor && <Badge>Child</Badge>}</h1><p>ID {p.identifier} · {p.age_years != null ? `${p.age_years} years` : "age not recorded"} · {p.preferred_language.toUpperCase()}{p.is_minor && p.guardian_name ? ` · Guardian: ${p.guardian_name}${p.guardian_relationship ? ` (${p.guardian_relationship})` : ""}` : ""}</p></div>
        <div className="button-row"><DownloadRecord patient={p} /><button className="button primary" onClick={() => start.mutate()} disabled={start.isPending || !!blocked}>{start.isPending ? "Starting…" : "Start new case"}</button></div></div>
      {blocked && <Notice>{blocked}</Notice>}
      {start.isError && <Notice error>{start.error.message}</Notice>}
      {p.notes && <Panel title="Notes"><p className="panel-padding">{p.notes}</p></Panel>}
      <HistoryPanel patientId={id} />
      <ConsentPanel patient={p} />
      <EditDetailsPanel patient={p} />
      <ErasePanel patient={p} />
    </>
  );
}

export function CasesPage() {
  const cases = useCases();
  const patients = usePatients();
  const names = new Map((patients.data ?? []).map((p) => [p.id, p.full_name]));
  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">PRACTITIONER REVIEW</span><h1>AI Case Workspace</h1><p>Take a case, retrieve cited book passages, and review candidate remedies.</p></div><Link className="button primary" href="/workspace/patients">Choose a patient</Link></div>
      <Notice>AI suggestions are decision support for a qualified practitioner. Every suggestion cites retrieved book text and requires your review. Nothing here is a diagnosis or a prescription.</Notice>
      {cases.isPending ? <Loading /> : cases.isError ? <Notice error>{cases.error.message}</Notice> : cases.data.length === 0 ? <Empty title="No cases yet">Open a patient and choose &ldquo;Start new case&rdquo;.</Empty> : (
        <Panel title="Recent cases" description={`${cases.data.length} total`}>
          <div className="registered-list">{cases.data.map((c) => <div key={c.id}><span><strong><Link className="text-link" href={casePath(c.id)}>{c.chief_complaint || "Untitled case"}</Link></strong> · {names.get(c.patient_id) ?? "Patient"}</span><Badge tone={statusTone[c.status]}>{statusLabel[c.status]}</Badge></div>)}</div>
        </Panel>
      )}
    </>
  );
}
