"use client";

import { Loader2, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api, call } from "@/lib/api/client";
import { setSession, useSession } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (session) router.replace("/inbox");
  }, [session, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.POST("/api/auth/login", { body: { email, password } }));
      setSession({ token: result.access_token, agent: result.agent });
      router.replace("/inbox");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed.");
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-sidebar p-12 text-sidebar-foreground lg:flex">
        <div className="flex items-center gap-2.5 text-sidebar-primary">
          <span className="flex size-8 items-center justify-center rounded-md bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground">
            UC
          </span>
          <span className="text-sm font-semibold tracking-wide">UnifyComm</span>
        </div>
        <div className="max-w-md space-y-5">
          <h1 className="text-3xl leading-tight font-semibold text-sidebar-primary text-balance">
            Every customer message, one calm workspace.
          </h1>
          <p className="text-sm leading-relaxed">
            WhatsApp, SMS and email land in one conversation per customer, triaged by intent
            and sentiment, with every outbound reply checked against consent, DND and channel
            rules before it leaves.
          </p>
        </div>
        <p className="flex items-center gap-2 text-xs">
          <ShieldCheck className="size-4" /> Replies are never sent automatically.
        </p>
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -bottom-24 size-96 rounded-full border border-sidebar-border"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-8 -bottom-8 size-64 rounded-full border border-sidebar-border"
        />
      </section>

      <section className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-6">
          <div className="space-y-1.5">
            <h2 className="text-xl font-semibold">Sign in</h2>
            <p className="text-sm text-muted-foreground">Agent workspace</p>
          </div>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="agent@unifycomm.local"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy && <Loader2 className="animate-spin" />}
            Sign in
          </Button>
        </form>
      </section>
    </main>
  );
}
