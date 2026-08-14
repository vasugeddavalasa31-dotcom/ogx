// Client-side session store — a drop-in replacement for the subset of
// `next-auth/react` this app used (SessionProvider, useSession, signIn,
// signOut). The session lives in a signed httpOnly cookie on the server;
// this module only mirrors it into React via the /api/auth/session endpoint.
//
// `data.accessToken` carries the gateway API key entered at login so existing
// consumers (useAuthClient etc.) keep working unchanged.

"use client";

import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

type SessionStatus = "loading" | "authenticated" | "unauthenticated";

interface SessionData {
  user?: { email?: string | null } | null;
  accessToken?: string | null;
  expires?: string;
}

interface SessionContextValue {
  data: SessionData | null;
  status: SessionStatus;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue>({
  data: null,
  status: "loading",
  refresh: async () => {},
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<SessionData | null>(null);
  const [status, setStatus] = useState<SessionStatus>("loading");

  const refresh = async () => {
    try {
      const res = await fetch("/api/auth/session", { cache: "no-store" });
      const session: SessionData | null = await res.json();
      setData(session);
      setStatus(session ? "authenticated" : "unauthenticated");
    } catch {
      setData(null);
      setStatus("unauthenticated");
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return createElement(
    SessionContext.Provider,
    { value: { data, status, refresh } },
    children
  );
}

export function useSession() {
  return useContext(SessionContext);
}

/**
 * Log in with the admin password + a gateway API key (mirrors the admin
 * dashboard). Resolves to `{ error }` on failure.
 */
export async function signIn(
  credentials: { email: string; password: string; gatewayKey: string },
  _options?: { callbackUrl?: string }
): Promise<{ error?: string }> {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });
    const body = await res.json();
    if (!res.ok) return { error: body.error ?? "Login failed" };
    return {};
  } catch {
    return { error: "Network error. Please try again." };
  }
}

export async function signOut(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    // Best effort — the session cookie expires on its own.
  }
}
