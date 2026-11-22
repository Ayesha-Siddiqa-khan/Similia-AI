# Phase 4 report: clinical workflows

Date: 2026-11-24. No paid or live provider call was made. The provider stop is still set. Decisions you gave: doctors may erase a patient with safeguards; minors need guardian consent.

## 1. What was inspected
Patient, consent, case, analysis and review routes and store; the proxy allow-list; the patient screens; the audit log use. Confirmed gaps: consent could never be withdrawn, patients could not be edited or restored from the screen, nothing could be exported or erased, earlier analyses were hidden, children had no safeguards, reads were not audited.

## 2. What was built (backend, tested)
- **Children:** under 18 (age from date of birth when known, else stated years) requires guardian name and relationship (create and edit). Analyses for children carry a paediatric caution. An **infant under 1 year is stopped** with an urgent-assessment red flag until the doctor confirms they assessed urgency; that flag stays visible afterwards.
- **Consent:** withdraw (stops all AI use, archives, deletes nothing), record again (new consent record, record reopens), consent history. New cases, edits, questions and analyses are refused for archived patients.
- **History:** per-patient case list (outcome, signed decision, remedy, date, no clinical detail), and all earlier analyses of a case (immutable, newest first).
- **Export:** one JSON document with patient, consents, cases, symptoms, analyses and reviews. Audited.
- **Erase:** permanent removal of the patient and everything under it. Only after the patient is archived and the identifier is typed exactly; owner only. The audit log keeps only "patient.erase", never the patient id or clinical content.
- **Audit coverage:** opening a patient, history or case is now logged (best effort: a failed log never blocks reading), plus consent, export and erase.
- Migration (not applied): `supabase/migrations/20261124100000_patient_safeguards.sql` adds two nullable guardian columns.

## 3. Frontend
Built with mocked requests only; no browser check yet.
- New patient form: optional date of birth; guardian fields appear and are required when the age or date of birth is under 18.
- Patients list hides archived records behind "Show archived"; badges for Child, Consent withdrawn, Archived.
- Patient page: case history, consent panel (withdraw with confirmation, record again, history), edit details, download record (JSON file, one request), and a separate erase section (only when archived, exact ID must be typed, redirects afterwards).
- Case page: paediatric caution above remedies, infant stop goes through the existing acknowledgement, earlier analyses (collapsed, loaded when opened), read-only notice for archived patients, autosave no longer retries on a 409.
- Tests: 167 frontend tests pass (23 new), ESLint and TypeScript clean (re-run by me).
- Known limits: the patient ID cannot be edited; a signed-off case of an archived patient still shows Reopen/review buttons (the backend refuses with its message). Operators can use practitioner endpoints (existing behaviour).

## 4. Needs your approval or action
1. Run the new migration in the Supabase SQL editor (project `ivlmduwdkwgrxqxjjuyg` only), after the two Phase 3 migrations.
2. The test patient and cases from earlier testing are still in your database. If you want them removed, use the new Erase screen or ask me for SQL; I will not delete them.
3. Legal wording: the consent text version `2026-11-v1` and the retention choice should be reviewed by someone qualified for your country before real patients are added.

## 5. Not done in Phase 4
Urdu for the remaining screens (results, review, AI settings, new patient screens), patient-facing portal, scheduled auto-erasure. Phase 5 (production readiness) is next.
