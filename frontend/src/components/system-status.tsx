"use client";

import { Activity } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useNow } from "@/hooks/use-now";
import { useHealth } from "@/lib/queries";
import { cn } from "@/lib/utils";

const WORKER_STALE_MS = 30_000;

type Tone = "ok" | "warn" | "off";

const CHANNEL_TEXT: Record<string, { text: string; tone: Tone }> = {
  ok: { text: "connected", tone: "ok" },
  configured: { text: "configured", tone: "ok" },
  starting: { text: "starting…", tone: "warn" },
  error: { text: "error (see worker log)", tone: "warn" },
  stale: { text: "no recent poll (worker down?)", tone: "warn" },
  no_public_url: { text: "no tunnel URL (PUBLIC_BASE_URL)", tone: "warn" },
  disabled: { text: "not configured", tone: "off" },
  not_configured: { text: "not configured", tone: "off" },
};

/** Worker heartbeat and channel health from /api/health (ARCHITECTURE §9.2, §14). */
export function SystemStatus() {
  const health = useHealth();
  const now = useNow(10_000);
  const data = health.data;
  const workerAge = data?.worker_heartbeat_at
    ? now - new Date(data.worker_heartbeat_at).getTime()
    : Infinity;
  const workerUp = workerAge < WORKER_STALE_MS;

  const rows: { label: string; text: string; tone: Tone }[] = data
    ? [
        {
          label: "Worker",
          text: workerUp ? `running (${data.ai_mode} models)` : "stopped: analysis is pending",
          tone: workerUp ? "ok" : "warn",
        },
        {
          label: "AI assistant",
          text: data.llm_configured ? "on" : "off (no OpenAI key)",
          tone: data.llm_configured ? "ok" : "off",
        },
        ...Object.entries(data.channels).map(([name, status]) => ({
          label: { simulator: "Simulator", gmail: "Gmail", twilio: "WhatsApp (Twilio)" }[name] ?? name,
          ...(CHANNEL_TEXT[status] ?? { text: status, tone: "warn" as Tone }),
        })),
      ]
    : [];
  const overall: Tone = !data
    ? "warn"
    : rows.some((r) => r.tone === "warn")
      ? "warn"
      : "ok";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          role="status"
          aria-label={overall === "ok" ? "All systems running" : "Some systems need attention"}
          data-testid="system-status"
          data-state={overall}
          className="relative flex size-8 items-center justify-center"
        >
          <Activity className="size-4" />
          <span
            className={cn(
              "absolute top-1 right-1 size-2 rounded-full",
              overall === "ok" ? "bg-ok" : "bg-warn",
            )}
          />
        </span>
      </TooltipTrigger>
      <TooltipContent side="right" className="w-64">
        {health.isError ? (
          <p>Cannot reach the API.</p>
        ) : (
          <dl className="space-y-1 text-xs">
            {rows.map((r) => (
              <div key={r.label} className="flex justify-between gap-3">
                <dt className="opacity-80">{r.label}</dt>
                <dd
                  className={cn(
                    "text-right font-medium",
                    r.tone === "warn" && "text-warn",
                    r.tone === "off" && "opacity-60",
                  )}
                >
                  {r.text}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
