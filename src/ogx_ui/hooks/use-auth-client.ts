import { useSession } from "@/lib/auth-session";
import { useMemo } from "react";
import OgxClient from "ogx-client";

export function useAuthClient() {
  const { data: session } = useSession();

  const client = useMemo(() => {
    const clientHostname =
      typeof window !== "undefined" ? window.location.origin : "";

    const options: any = {
      baseURL: `${clientHostname}/api`,
    };

    if (session?.accessToken) {
      options.apiKey = session.accessToken;
    }

    return new OgxClient(options);
  }, [session?.accessToken]);

  return client;
}
