export function isOperator(metadata: Record<string, unknown> | undefined): boolean {
  return metadata?.similia_role === "operator" || metadata?.similia_role === "admin";
}

/** Practitioners take patient cases; operators and admins may too. */
export function isPractitioner(metadata: Record<string, unknown> | undefined): boolean {
  return metadata?.similia_role === "practitioner" || isOperator(metadata);
}

export function sameOrigin(request: Request): boolean {
  return request.headers.get("origin") === new URL(request.url).origin;
}
