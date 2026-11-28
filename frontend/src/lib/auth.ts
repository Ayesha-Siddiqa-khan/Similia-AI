export function isOperator(metadata: Record<string, unknown> | undefined): boolean {
  return metadata?.similia_role === "operator" || metadata?.similia_role === "admin";
}

/** Practitioners take patient cases; operators and admins may too. */
export function isPractitioner(metadata: Record<string, unknown> | undefined): boolean {
  return metadata?.similia_role === "practitioner" || isOperator(metadata);
}

export function sameOrigin(request: Request): boolean {
  const expectedOrigin = process.env.SIMILIA_DESKTOP_ORIGIN ?? new URL(request.url).origin;
  return request.headers.get("origin") === expectedOrigin;
}
