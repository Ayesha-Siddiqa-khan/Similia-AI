import { createHmac } from "node:crypto";
import { once } from "node:events";
import http from "node:http";

const user = {
  id: "9639a8dd-0524-4ade-9c06-d26a8dd68fe9", aud: "authenticated", role: "authenticated",
  email: "desktop-test@example.test", app_metadata: { similia_role: "practitioner" }, user_metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};
const patient = {
  id: "ec3edea1-b038-4571-811d-1f67e3e466a5", full_name: "Synthetic Patient",
  identifier: "SYNTHETIC-1", preferred_language: "en", sex: "unknown",
  created_at: user.created_at, updated_at: user.created_at,
};

export async function startFixture(metadata) {
  const url = new URL(metadata.supabaseUrl);
  if (url.hostname !== "127.0.0.1") return null;
  const record = {
    id: "2999a182-1a3f-41bb-9c09-3e4f4bc97c33", patient_id: patient.id, status: "draft",
    chief_complaint: "Synthetic desktop case", language: "en", created_at: user.created_at,
    updated_at: user.created_at,
  };
  const expires_at = Math.floor(Date.now() / 1000) + 3600;
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const unsigned = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: user.id, aud: user.aud, exp: expires_at })}`;
  const token = `${unsigned}.${createHmac("sha256", "fixture-only").update(unsigned).digest("base64url")}`;
  const server = http.createServer(async (request, response) => {
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Access-Control-Allow-Headers", request.headers["access-control-request-headers"] || "*");
    response.setHeader("Content-Type", "application/json");
    if (request.method === "OPTIONS") return response.writeHead(204).end();
    const route = new URL(request.url, url);
    const send = (data, status = 200) => response.writeHead(status).end(JSON.stringify(data));
    const read = async () => {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      return JSON.parse(Buffer.concat(chunks).toString("utf8"));
    };
    try {
      if (route.pathname === "/auth/v1/token" && request.method === "POST") {
        const credentials = await read();
        if (credentials.email !== user.email || credentials.password !== "offline-test") return send({}, 401);
        return send({ access_token: token, refresh_token: "fixture-refresh", token_type: "bearer", expires_in: 3600, expires_at, user });
      }
      if (route.pathname === "/auth/v1/user") {
        return request.headers.authorization === `Bearer ${token}` ? send(user) : send({}, 401);
      }
      if (route.pathname.startsWith("/rest/v1/") && request.headers.apikey === "offline-test-service-role") {
        if (route.pathname === "/rest/v1/cases") {
          if (route.searchParams.get("practitioner_id") !== `eq.${user.id}`) return send([], 403);
          if (request.method === "PATCH") record.chief_complaint = (await read()).chief_complaint;
          return send([record]);
        }
        if (route.pathname === "/rest/v1/patients") return send([patient]);
        return send([]);
      }
      return send({}, 404);
    } catch {
      return send({}, 400);
    }
  });
  server.listen(Number(url.port), "127.0.0.1");
  await once(server, "listening");
  return server;
}
