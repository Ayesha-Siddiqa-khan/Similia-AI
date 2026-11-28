"use client";

import { useState, type FormEvent } from "react";
import Image from "next/image";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ProgressDots } from "@/components/progress-dots";
import { Notice } from "@/components/ui";
import { api } from "@/lib/backend";
import { del, post, put } from "./api";
import { clinicalQueryKey } from "./clinical-api";

type Photo = {
  id: string; case_id: string; body_site: string; side: string; captured_on: string;
  complaint: string; notes: string;
};
type PhotoFinding = {
  id: string; model: string; image_ids: string[]; created_at: string;
  payload: { observations: string[]; limits: string[] };
};
const sites = ["neck", "shoulder", "upper arm", "elbow", "forearm", "wrist", "hand", "fingers",
  "chest", "abdomen", "back", "hip", "thigh", "knee", "lower leg", "ankle", "foot", "toes"];
const fileUrl = (photo: Photo, size: "thumb" | "full") =>
  `/api/backend/cases/${photo.case_id}/photos/${photo.id}/${size}`;

export function ClinicalPhotos({ caseId, locked }: { caseId: string; locked: boolean }) {
  const client = useQueryClient();
  const path = `cases/${caseId}/photos`;
  const queryKey = ["clinical-photos", caseId];
  const query = useQuery({
    queryKey, retry: false,
    queryFn: ({ signal }) => api<{
      collection: boolean; gemini: boolean; vision_model: string | null;
      images: Photo[]; findings: PhotoFinding[];
    }>(path, { signal }),
  });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [replacement, setReplacement] = useState<Photo | null>(null);
  const [viewer, setViewer] = useState<Photo | null>(null);
  const [consentForm, setConsentForm] = useState<"collection" | "gemini" | null>(null);
  const [formVersion, setFormVersion] = useState(0);
  const mutation = useMutation({
    mutationFn: (operation: () => Promise<unknown>) => operation(),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["clinical-photos"] });
      void client.invalidateQueries({ queryKey: clinicalQueryKey(caseId) });
    },
  });
  if (query.isPending) return <p role="status">Loading clinical photos…</p>;
  if (query.isError) return <Notice error>{query.error.message}</Notice>;
  const { collection, gemini, vision_model: model, images, findings } = query.data;
  const selection = images.filter((item) => selectedIds.includes(item.id))
    .sort((a, b) => a.captured_on.localeCompare(b.captured_on));
  const relevantFindings = findings.filter((item) => !selection.length || (
    item.image_ids.length === selection.length && selection.every((photo) => item.image_ids.includes(photo.id))
  ));

  function updateConsent(scope: "collection" | "gemini", granted: boolean) {
    mutation.mutate(() => put(`${path}/consent`, { scope, granted }), {
      onSuccess: () => setConsentForm(null),
    });
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (replacement) data.set("replaces_id", replacement.id);
    mutation.mutate(() => api(path, { method: "POST", body: data }), {
      onSuccess: () => {
        setReplacement(null);
        setFormVersion((value) => value + 1);
      },
    });
  }

  return <section className="clinical-photos stack" aria-label="Clinical photos">
    <h3>Clinical photos</h3>
    {mutation.isPending && <p role="status">Working <ProgressDots /></p>}
    {mutation.isError && <Notice error>{mutation.error.message}</Notice>}
    {!locked && <div className="stack">
      <div className="button-row">
        <button type="button" className="button secondary" disabled={mutation.isPending} onClick={() => collection ? updateConsent("collection", false) : setConsentForm("collection")}>{collection ? "Withdraw collection consent" : "Record collection consent"}</button>
        <button type="button" className="button secondary" disabled={!collection || mutation.isPending} onClick={() => gemini ? updateConsent("gemini", false) : setConsentForm("gemini")}>{gemini ? "Withdraw Gemini consent" : "Record Gemini consent"}</button>
      </div>
      {consentForm && <form className="stack" onSubmit={(event) => { event.preventDefault(); updateConsent(consentForm, true); }}>
        <label className="clinical-check"><input type="checkbox" required /> {consentForm === "collection"
          ? "The patient or guardian has agreed to collect and store affected-area photos privately."
          : "The patient or guardian has agreed to send selected affected-area photos to Google Gemini for AI observations."}</label>
        <div className="button-row"><button className="button primary" disabled={mutation.isPending}>Save consent</button>
          <button type="button" className="button secondary" onClick={() => setConsentForm(null)}>Cancel</button></div>
      </form>}
      {collection && <form key={replacement?.id ?? formVersion} className="stack" onSubmit={upload}>
        {replacement && <Notice>Replacing the {replacement.body_site} photo from {replacement.captured_on}. The earlier photo will be archived.</Notice>}
        <div className="clinical-grid">
          <label className="field">Affected-area photo<input name="file" type="file" accept="image/jpeg,image/png,image/webp" required /></label>
          <label className="field">Body site<select name="body_site" required defaultValue={replacement?.body_site ?? ""}>
            <option value="">Choose body site</option>{sites.map((site) => <option key={site}>{site}</option>)}
          </select></label>
          <label className="field">Side<select name="side" defaultValue={replacement?.side ?? "unspecified"}>
            {["unspecified", "left", "right", "both", "midline"].map((side) => <option key={side}>{side}</option>)}
          </select></label>
          <label className="field">Capture date<input name="captured_on" type="date" required defaultValue={replacement?.captured_on} /></label>
          <label className="field">Associated complaint<input name="complaint" required maxLength={160} defaultValue={replacement?.complaint} /></label>
          <label className="field">Notes<input name="notes" maxLength={1000} defaultValue={replacement?.notes} /></label>
        </div>
        <label className="clinical-check"><input type="checkbox" name="affected_area_only" value="true" required /> The photo shows only the affected area, with no face or identifying details.</label>
        <div className="button-row">
          <button className="button primary" disabled={mutation.isPending}>{replacement ? "Replace photo" : "Add photo"}</button>
          {replacement && <button type="button" className="button secondary" onClick={() => setReplacement(null)}>Cancel replacement</button>}
        </div>
      </form>}
    </div>}
    {images.length > 0 && <div className="clinical-photo-list">
      {images.map((photo) => {
        const selected = selectedIds.includes(photo.id);
        const incompatible = !selected && selection.some((item) => item.body_site !== photo.body_site || item.side !== photo.side);
        return <figure key={photo.id} className="clinical-photo">
          <button className="clinical-image-button" type="button" aria-label={`View ${photo.body_site} photo from ${photo.captured_on}`} onClick={() => setViewer(photo)}>
            <Image width={200} height={150} src={fileUrl(photo, "thumb")} alt={`${photo.body_site} affected area`} unoptimized />
          </button>
          <figcaption><strong>{photo.body_site} · {photo.side}</strong><br />{photo.captured_on} · {photo.complaint}{photo.notes && <><br />{photo.notes}</>}</figcaption>
          <button type="button" className="button secondary" aria-pressed={selected} disabled={incompatible || (!selected && selection.length === 2)} onClick={() => setSelectedIds(
            selected ? selectedIds.filter((id) => id !== photo.id) : [...selectedIds.filter((id) => images.some((item) => item.id === id)), photo.id],
          )}>{selected ? "Deselect photo" : "Select photo"}</button>
          {!locked && photo.case_id === caseId && <div className="button-row">
            <button type="button" className="text-link" disabled={mutation.isPending || !collection} onClick={() => setReplacement(photo)}>Replace</button>
            <button type="button" className="text-link" disabled={mutation.isPending} onClick={() => {
              if (window.confirm("Archive this clinical photo?")) {
                mutation.mutate(() => del(`${path}/${photo.id}`), { onSuccess: () => {
                  setSelectedIds((ids) => ids.filter((id) => id !== photo.id));
                  if (viewer?.id === photo.id) setViewer(null);
                } });
              }
            }}>Archive</button>
          </div>}
        </figure>;
      })}
    </div>}
    {viewer && <div className="stack">
      <div className="button-row"><strong>{viewer.body_site} · {viewer.captured_on}</strong><button type="button" className="button secondary" onClick={() => setViewer(null)}>Close full-size photo</button></div>
      <Image className="clinical-full-photo" width={960} height={720} src={fileUrl(viewer, "full")} alt={`${viewer.body_site} affected area, ${viewer.captured_on}`} unoptimized />
    </div>}
    {selection.length === 2 && <div className="stack">
      <h4>Follow-up comparison</h4>
      <Notice>Differences in lighting, angle, scale or image quality can make changes difficult to assess.</Notice>
      <div className="clinical-grid">
        {selection.map((photo) => <figure key={photo.id}>
          <Image className="clinical-full-photo" width={500} height={360} src={fileUrl(photo, "full")} alt={`${photo.body_site} affected area, ${photo.captured_on}`} unoptimized />
          <figcaption>{photo.captured_on}{photo.notes && <> · {photo.notes}</>}</figcaption>
        </figure>)}
      </div>
    </div>}
    {!locked && gemini && selection.length > 0 && <div>
      {model ? <button type="button" className="button primary" disabled={mutation.isPending || !selection.some((item) => item.case_id === caseId)} onClick={() => mutation.mutate(() =>
        post(`${path}/observe`, { image_ids: selection.map((photo) => photo.id), model }),
      )}>{selection.length === 2 ? "Compare" : "Describe"} with Gemini · {model}</button>
        : <p className="fine-print">Select a verified Gemini image model in AI Settings to run photo observations.</p>}
    </div>}
    {relevantFindings.map((finding) => <section key={finding.id} className="stack">
      <h4>AI photo observations</h4>
      <p className="fine-print">Gemini · {finding.model} · {new Date(finding.created_at).toLocaleString()}</p>
      <ul>{finding.payload.observations.map((text, i) => <li key={i}>{text}</li>)}</ul>
      {finding.payload.limits.length > 0 && <Notice>{finding.payload.limits.join(" ")}</Notice>}
    </section>)}
  </section>;
}
