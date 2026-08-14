// Server-side session helpers for the OGX UI.
//
// Mirrors the admin-dashboard login style (a shared admin password + a
// super-admin email allowlist, no external OAuth) and additionally carries the
// gateway API key the user enters on the login form, so proxied API calls can
// authenticate against the OrbiterX gateway.
//
// The session is a signed (HMAC) httpOnly cookie — never exposed to the
// client. `gatewayKey` is read only by the server-side proxy.

import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";

const SESSION_COOKIE = "ogx_ui_session";
const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60; // 8h, matches the admin dashboard

// Admin dashboard defaults, overridable via env.
export const SUPER_ADMIN_EMAILS = (
  process.env.OGX_UI_ADMIN_EMAILS ??
  "vasugeddavalasa31@gmail.com,ojas@orbiterxai.online,admin@orbiterxai.online"
)
  .split(",")
  .map(s => s.trim())
  .filter(Boolean);

export const ADMIN_PASSWORD =
  process.env.OGX_UI_ADMIN_PASSWORD || "orbiterx-admin-2025";

export function isSuperAdmin(email: string): boolean {
  return SUPER_ADMIN_EMAILS.includes(email);
}

export interface AdminSession {
  email: string;
  gatewayKey: string;
}

function secretKey(): Uint8Array {
  const secret =
    process.env.OGX_UI_SESSION_SECRET || "ogx-ui-session-secret-32-byte!";
  return new TextEncoder().encode(secret);
}

export async function createSession(data: AdminSession): Promise<void> {
  const token = await new SignJWT({
    email: data.email,
    gatewayKey: data.gatewayKey,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_MAX_AGE_SECONDS}s`)
    .sign(secretKey());

  const store = await cookies();
  store.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

export async function getSession(): Promise<AdminSession | null> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, secretKey());
    if (
      typeof payload.email === "string" &&
      typeof payload.gatewayKey === "string"
    ) {
      return { email: payload.email, gatewayKey: payload.gatewayKey };
    }
    return null;
  } catch {
    return null;
  }
}

export async function destroySession(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}
