"use client";

import type { TextareaHTMLAttributes } from "react";

interface Props extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "rows"> {
  /** Smallest height, in text lines. The box grows beyond this by itself as the text grows. */
  minRows?: number;
}

/**
 * A text box that always fits its text. The browser sizes it (no scripts): an invisible copy of the
 * text sits in the same grid cell, so the box grows with typing, pasted or dictated text, saved text,
 * the grey example text, a late-loading font, and a resized window.
 */
export function AutoTextarea({ minRows = 3, value, placeholder, className = "", ...rest }: Props) {
  const text = typeof value === "string" ? value : String(value ?? "");
  // The trailing newline keeps room for a last empty line; the placeholder counts while the box is empty.
  const mirror = `${text || placeholder || ""}\n`;
  return (
    <div className="grow-wrap" data-replicated-value={mirror}>
      <textarea rows={minRows} value={value} placeholder={placeholder} className={`auto-textarea ${className}`} {...rest} />
    </div>
  );
}
