import { GraphQLClient } from "graphql-request";

let client: GraphQLClient | null = null;

/** Shared GraphQL client for the FastAPI /graphql endpoint. */
export function getGraphQLClient(): GraphQLClient {
  const baseUrl = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  client ??= new GraphQLClient(`${baseUrl}/graphql`, {
    headers: process.env.SIMILIA_DESKTOP_TOKEN
      ? { "X-Similia-Desktop-Token": process.env.SIMILIA_DESKTOP_TOKEN }
      : undefined,
    fetch: (url, init) => fetch(url, { ...init, signal: AbortSignal.timeout(5000), cache: "no-store" }),
  });
  return client;
}
