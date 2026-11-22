import { z } from "zod";

export const GUARDIAN_MESSAGE = "Patients under 18 need a guardian's name and relationship. Record who gave consent on the patient's behalf.";

/** Whole years between a YYYY-MM-DD date of birth and today, or null when the date is not valid. */
export function ageFromBirthDate(dob: string, now = new Date()): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dob);
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  let age = now.getFullYear() - year;
  if (now.getMonth() + 1 < month || (now.getMonth() + 1 === month && now.getDate() < day)) age -= 1;
  return age;
}

/** Same rule as the backend: the date of birth decides when given, otherwise the typed age. */
export function isMinorAge(age: number | null | undefined, dob: string | null | undefined, now = new Date()): boolean {
  const fromDob = dob ? ageFromBirthDate(dob, now) : null;
  const years = fromDob ?? (typeof age === "number" && Number.isFinite(age) ? age : null);
  return years !== null && years < 18;
}

/** Fields shared by the new-patient and edit forms. */
export const guardianShape = {
  date_of_birth: z.string().refine((v) => v === "" || ageFromBirthDate(v) !== null, "Enter a valid date.").refine((v) => v === "" || (ageFromBirthDate(v) ?? 0) >= 0, "The date of birth cannot be in the future."),
  guardian_name: z.string().max(200, "Use 200 characters or fewer."),
  guardian_relationship: z.string().max(100, "Use 100 characters or fewer."),
};

/** Fields the new-patient and edit forms have in common. Limits match the backend (PatientCreate). */
export const personalShape = {
  full_name: z.string().trim().min(1, "Enter the patient's name.").max(200, "Use 200 characters or fewer."),
  age_years: z.number().int("Use a whole number.").min(0, "Age cannot be negative.").max(130, "Enter a realistic age.").nullable(),
  sex: z.enum(["unspecified", "female", "male", "other"]),
  preferred_language: z.enum(["en", "hi", "ur"]),
  contact: z.string().max(200, "Use 200 characters or fewer."),
  notes: z.string().max(4000, "Use 4,000 characters or fewer."),
  ...guardianShape,
};

/** Adds the "children need a guardian" rule to a form schema. */
export function requireGuardianForMinors(value: { age_years: number | null; date_of_birth: string; guardian_name: string; guardian_relationship: string }, ctx: z.RefinementCtx) {
  if (!isMinorAge(value.age_years, value.date_of_birth)) return;
  if (!value.guardian_name.trim()) ctx.addIssue({ code: "custom", path: ["guardian_name"], message: GUARDIAN_MESSAGE });
  if (!value.guardian_relationship.trim()) ctx.addIssue({ code: "custom", path: ["guardian_relationship"], message: GUARDIAN_MESSAGE });
}

/** The values sent to the backend: a minor sends guardian details, an adult sends none. */
export function guardianPayload(value: { age_years: number | null; date_of_birth: string; guardian_name: string; guardian_relationship: string }) {
  const minor = isMinorAge(value.age_years, value.date_of_birth);
  return {
    date_of_birth: value.date_of_birth || null,
    guardian_name: minor ? value.guardian_name.trim() : null,
    guardian_relationship: minor ? value.guardian_relationship.trim() : null,
  };
}
