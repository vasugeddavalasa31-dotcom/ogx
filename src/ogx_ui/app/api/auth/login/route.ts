import { NextRequest, NextResponse } from "next/server";
import { ADMIN_PASSWORD, createSession, isSuperAdmin } from "@/lib/server-auth";

export async function POST(request: NextRequest) {
  let body: { email?: string; password?: string; gatewayKey?: string } = {};
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const email = body.email?.trim() ?? "";
  const password = body.password ?? "";
  const gatewayKey = body.gatewayKey?.trim() ?? "";

  if (password !== ADMIN_PASSWORD) {
    return NextResponse.json({ error: "Incorrect password" }, { status: 401 });
  }
  if (!isSuperAdmin(email)) {
    return NextResponse.json({ error: "Not authorized" }, { status: 403 });
  }
  if (!gatewayKey) {
    return NextResponse.json(
      { error: "Gateway API key is required" },
      { status: 400 }
    );
  }

  await createSession({ email, gatewayKey });
  return NextResponse.json({ ok: true, email });
}
