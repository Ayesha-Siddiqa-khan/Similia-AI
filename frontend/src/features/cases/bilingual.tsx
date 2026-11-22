// English first; when Urdu is switched on, the Urdu follows in the same text.
export function Bi({ en, ur, show }: { en: string; ur: string; show: boolean }) {
  return <>{en}{show && <> · <bdi className="urdu-inline" lang="ur" dir="rtl">{ur}</bdi></>}</>;
}
/** The same idea for plain strings (placeholders, option labels). */
export const both = (en: string, ur: string, show: boolean, sep = " · ") => (show ? `${en}${sep}${ur}` : en);
/** A full-width Urdu line under an English paragraph. */
export function UrduLine({ text, show }: { text: string; show: boolean }) {
  return show ? <bdi className="urdu-inline urdu-block" lang="ur" dir="rtl">{text}</bdi> : null;
}
