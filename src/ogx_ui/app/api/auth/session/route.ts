import { NextResponse } from "next/server";
import { getSession } from "@/lib/server-auth";

// Same shape as NextAuth's /api/auth/session so the client session store
// (lib/auth-session) can treat it identically: `null` when signed out,
// otherwise `{ user, accessToken }` where accessToken is the gateway key.
export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json(null);
  return NextResponse.json({
    user: { email: session.email },
    accessToken: session.gatewayKey,
  });
}
