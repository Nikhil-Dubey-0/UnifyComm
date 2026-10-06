"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { NavRail } from "@/components/nav-rail";
import { useSession } from "@/lib/auth";
import { useLiveUpdates } from "@/lib/ws";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  useLiveUpdates(session?.token, queryClient);

  useEffect(() => {
    if (session === null) {
      queryClient.clear();
      router.replace("/login");
    }
  }, [session, router, queryClient]);

  if (!session) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" aria-label="Loading" />
      </div>
    );
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <NavRail agentName={session.agent.name} />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
