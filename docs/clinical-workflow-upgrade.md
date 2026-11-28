# Similia AI clinical workflow

The case workspace preserves legacy analyses and adds three independently versioned reports. Each uses a snapshot of the recorded case. The evidence catalog is maintained by the clinic. Replaced and removed photos are archived privately and enter the existing authorised erasure workflow.

## Delivery order

1. Add owner-scoped reports, attempt tracking, provenance, and authenticated endpoints through additive migrations. Keep exports and history available for each saved version.
2. Extend the existing retrieval adapters with cross-book Repertory and Materia Medica research, verified citations, and per-search mode and coverage. Retain existing vectors. Save an urgent handoff even when search is skipped, and allow unranked references after explicit practitioner review.
3. Generate an AI draft from a saved research version. Ground clinical fields in a versioned clinic-approved guideline catalog. Keep historical associations identified as such, and suppress rankings for urgent cases. Require explicit clinician review and signing for the final report, with independent authoring available.
4. Add affected-area photos, private storage, collection consent and named-provider AI authorisation. Preserve visible-only observations separately from reported symptoms and support longitudinal comparison by body site.
5. Verify access boundaries, failures, retention, signing, search provenance and all three English and Urdu export layouts. Check ingestion before restarting. Apply database changes and run a live case only with explicit authorisation. Roll back by disabling the new workspace while preserving stored records.

## Setup and rollout

1. Review `supabase/migrations/20261124200000_clinical_workflow.sql` against the target schema. Apply it only in an approved environment. It adds private tables and the `clinical-images` bucket. Keep browser roles denied direct access to these records and objects.
2. Grant `app_metadata.similia_clinical_signing = true` through Auth administration to individually verified clinicians. Preserve their existing role and metadata. Case ownership is also required. Confirm that an operator without this grant cannot sign.
3. Have the clinic populate `clinical_guidelines` with approved excerpts. Each entry requires the title, publisher, edition, section, HTTPS source URL, exact excerpt, approving clinician UUID, approval date and review-due date. Use a new row for each revised excerpt and retire the previous row with `retired_at`. Expired and retired guidance is excluded from new assessments. The app displays unavailable guidance when there is no matching approved evidence.
4. Set `CLINICAL_GEMINI_VISION_MODELS` to a comma-separated list of exact Gemini model IDs verified for image input and JSON output. An empty list disables photo inference. Practitioners select a listed model using their existing active Gemini key in AI Settings. Photo uploads and manual comparison can be used without a Gemini key. Verify the clinic permits the provider and model before sending any patient image.
5. Check the operator monitor for pending or running ingestion and the auto-resume queue before restarting. Keep `CLINICAL_WORKFLOW_ENABLED=false` until the migration and permission checks pass. Enable it in the backend for the approved environment, open a case and go to **Analyse → Clinical reports**. Photo collection starts under **Chief complaint**. Use redacted request logging and disable raw access logs that include record identifiers.

## Verification and recovery

- Use two practitioner accounts to check report and photo isolation through both the app and direct Supabase requests. Verify an upload, same-site comparison, replacement, archival, consent withdrawal, patient export and authorised erasure in the approved test environment. Test interrupted writes and duplicate submissions. Verify a failed photo publication leaves earlier active photos intact.
- Confirm the urgent handoff is visible in all relevant versions and their exports. Have an authorised practitioner record a disposition and check that the reference search returns no remedy ranking. Verify report updates create independent versions and edits to the case require a fresh review before signing from an earlier assessment.
- Check all three reports in English and Urdu. AI Urdu translations preserve original cited excerpts and urgent warnings. The clinician enters and reviews each language version of the final report before signing it. Use a test record until explicit approval covers use of the saved patient case and any provider quota.
- If an upload unexpectedly stopped and its row is still `uploading`, confirm no worker can resume the upload before reconciling the reserved row and its private objects. An authorised patient erasure includes reserved and archived records. If deletion of private objects fails, retry the same erasure. A record with erasure pending stays archived.
- Disable `CLINICAL_WORKFLOW_ENABLED` to restore the legacy UI during rollback. Retain the additive schema and private objects so the patient export and erasure paths continue to cover saved clinical records.
