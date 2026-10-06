import { AlertTriangle, Sparkles } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { AiResult, Message } from "@/lib/api/client";
import { humanize, percent } from "@/lib/format";
import { cn } from "@/lib/utils";

const CHIP = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium";

/** Intent and sentiment for one inbound message, each pending, ok or unavailable. */
export function AiChips({ ai }: { ai: Message["ai"] }) {
  if (!ai.intent && !ai.sentiment) {
    return (
      <span data-testid="ai-pending" className={cn(CHIP, "bg-ai/8 text-ai")}>
        <Sparkles className="size-3 animate-pulse" />
        Analysis pending
      </span>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="ai-chips">
      <IntentChip result={ai.intent} />
      <SentimentChip result={ai.sentiment} />
    </div>
  );
}

function Unavailable({ what, result }: { what: string; result: AiResult }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn(CHIP, "bg-muted text-muted-foreground")}>
          <AlertTriangle className="size-3" />
          {what} unavailable
        </span>
      </TooltipTrigger>
      <TooltipContent>{result.error ?? "The model could not run."}</TooltipContent>
    </Tooltip>
  );
}

function ModelLine({ result }: { result: AiResult }) {
  return (
    <p className="mt-1.5 text-[10px] opacity-70">
      {result.model_name} · {result.model_version}
      {result.latency_ms != null && ` · ${result.latency_ms} ms`}
    </p>
  );
}

export function IntentChip({ result }: { result: AiResult | null | undefined }) {
  if (!result) {
    return <span className={cn(CHIP, "bg-ai/8 text-ai")}>Intent pending</span>;
  }
  if (result.status === "error" || !result.label) {
    return <Unavailable what="Intent" result={result} />;
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            CHIP,
            result.needs_review ? "bg-warn/15 text-[oklch(0.48_0.11_70)]" : "bg-ai/10 text-ai",
          )}
        >
          <Sparkles className="size-3" />
          {result.needs_review ? "Needs review" : (result.category_queue ?? "Intent")}
          <span className="font-normal opacity-80">· {humanize(result.label)}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">
        <p className="mb-1 font-medium">Top intents</p>
        <ul className="space-y-0.5">
          {(result.top_k ?? []).map((s) => (
            <li key={s.label} className="flex justify-between gap-4">
              <span>{humanize(s.label)}</span>
              <span className="tabular">{percent(s.confidence)}</span>
            </li>
          ))}
        </ul>
        <ModelLine result={result} />
      </TooltipContent>
    </Tooltip>
  );
}

const SENTIMENT_STYLE: Record<string, string> = {
  negative: "bg-urgent/10 text-urgent",
  neutral: "bg-muted text-muted-foreground",
  positive: "bg-ok/12 text-ok",
};

export function SentimentChip({ result }: { result: AiResult | null | undefined }) {
  if (!result) {
    return <span className={cn(CHIP, "bg-ai/8 text-ai")}>Sentiment pending</span>;
  }
  if (result.status === "error" || !result.label) {
    return <Unavailable what="Sentiment" result={result} />;
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn(CHIP, SENTIMENT_STYLE[result.label] ?? SENTIMENT_STYLE.neutral)}>
          {humanize(result.label)}
          <span className="tabular font-normal opacity-80">{percent(result.confidence)}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Sentiment
        <ModelLine result={result} />
      </TooltipContent>
    </Tooltip>
  );
}
