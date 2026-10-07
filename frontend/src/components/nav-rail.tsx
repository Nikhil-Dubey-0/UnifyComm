"use client";

import { Inbox, LogOut, ShieldCheck, SlidersHorizontal, Smartphone, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { clearSession } from "@/lib/auth";
import { initials } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type LiveStatus, useLiveStatus } from "@/lib/ws";

const NAV = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/admin/preferences", label: "Channel preferences", icon: SlidersHorizontal },
  { href: "/admin/compliance", label: "Compliance log", icon: ShieldCheck },
  { href: "/simulator", label: "Customer simulator", icon: Smartphone },
];

const LIVE_TEXT: Record<LiveStatus, string> = {
  open: "Live updates connected",
  connecting: "Connecting to live updates…",
  closed: "Live updates offline, reconnecting",
};

export function NavRail({ agentName }: { agentName: string }) {
  const pathname = usePathname();
  const live = useLiveStatus();

  return (
    <nav
      aria-label="Main"
      className="flex w-16 shrink-0 flex-col items-center gap-1 bg-sidebar py-4 text-sidebar-foreground"
    >
      <Link
        href="/inbox"
        className="mb-4 flex size-9 items-center justify-center rounded-md bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground"
        aria-label="UnifyComm home"
      >
        UC
      </Link>
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Tooltip key={href}>
            <TooltipTrigger asChild>
              <Link
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex size-10 items-center justify-center rounded-md transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                )}
              >
                <Icon className="size-5" />
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
          </Tooltip>
        );
      })}

      <div className="mt-auto flex flex-col items-center gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              role="status"
              aria-label={LIVE_TEXT[live]}
              data-testid="live-status"
              data-state={live}
              className="flex size-6 items-center justify-center"
            >
              <span
                className={cn(
                  "size-2.5 rounded-full",
                  live === "open" && "bg-ok shadow-[0_0_0_3px] shadow-ok/25",
                  live === "connecting" && "animate-pulse bg-warn",
                  live === "closed" && "bg-urgent",
                )}
              />
            </span>
          </TooltipTrigger>
          <TooltipContent side="right">{LIVE_TEXT[live]}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="flex size-8 items-center justify-center rounded-full bg-sidebar-accent text-[11px] font-semibold text-sidebar-accent-foreground">
              {initials(agentName)}
            </span>
          </TooltipTrigger>
          <TooltipContent side="right">Signed in as {agentName}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={clearSession}
              aria-label="Sign out"
              className="flex size-9 items-center justify-center rounded-md hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
            >
              <LogOut className="size-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Sign out</TooltipContent>
        </Tooltip>
      </div>
    </nav>
  );
}
