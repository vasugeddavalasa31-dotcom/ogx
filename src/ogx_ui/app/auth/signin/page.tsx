"use client";

import { signIn, signOut, useSession } from "@/lib/auth-session";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { KeyRound, LogOut, User } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function SignInPage() {
  const { data: session, status, refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [gatewayKey, setGatewayKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const result = await signIn({ email, password, gatewayKey });
    setLoading(false);
    if (result?.error) {
      setError(result.error);
      return;
    }
    await refresh();
    router.push("/");
    router.refresh();
  };

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen">
      <Card className="w-[420px]">
        <CardHeader>
          <CardTitle>Authentication</CardTitle>
          <CardDescription>
            {session
              ? `Signed in as ${session.user?.email}`
              : "Sign in with your admin credentials and a gateway API key"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!session ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm text-muted-foreground block">
                  Admin email
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="admin@orbiterxai.online"
                  className="w-full p-2 border rounded text-sm"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-muted-foreground block">
                  Password
                </label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full p-2 border rounded text-sm"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-muted-foreground block">
                  Gateway API key
                </label>
                <input
                  type="password"
                  required
                  value={gatewayKey}
                  onChange={e => setGatewayKey(e.target.value)}
                  placeholder="sk-... or your OrbiterX key"
                  className="w-full p-2 border rounded text-sm"
                />
              </div>
              {error && <div className="text-sm text-red-600">{error}</div>}
              <Button type="submit" disabled={loading} className="w-full">
                <User className="mr-2 h-4 w-4" />
                {loading ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="text-sm text-muted-foreground">
                Signed in as {session.user?.email}
              </div>
              <div className="text-xs text-muted-foreground">
                The gateway key you entered is used for API calls to the
                OrbiterX gateway.
              </div>
              <div className="flex gap-2">
                <Button onClick={() => router.push("/")} className="flex-1">
                  Go to Dashboard
                </Button>
                <Button
                  onClick={async () => {
                    await signOut();
                    await refresh();
                  }}
                  variant="outline"
                  className="flex-1"
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign out
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
