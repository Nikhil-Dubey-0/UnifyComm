"use client";

import { BadgeCheck, Inbox, Loader2, Search } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  CategoryBadge,
  ChannelIcon,
  PRIORITY_STRIPE,
  PriorityBadge,
  StatusBadge,
} from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useNow } from "@/hooks/use-now";
import type { ConversationListItem, ConversationStatus, Priority } from "@/lib/api/client";
import { CATEGORY_QUEUES, PRIORITY_LABEL, timeAgo } from "@/lib/format";
import { type ConversationFilters, type InboxSort, useConversations } from "@/lib/queries";
import { cn } from "@/lib/utils";

const STATUS_TABS: { value: ConversationStatus | "all"; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "pending", label: "Pending" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

const ANY = "any";

const SORT_KEY = "unifycomm.inbox.sort";
const SORTS: { value: InboxSort; label: string; hint: string }[] = [
  { value: "newest", label: "Newest", hint: "Latest activity first" },
  {
    value: "waiting",
    label: "Most urgent",
    hint: "Urgent priority first, then the customers who have waited longest (support-desk order)",
  },
];

export function ConversationList() {
  const params = useParams<{ conversationId?: string }>();
  const selectedId = params.conversationId ? Number(params.conversationId) : null;

  const [sort, setSort] = useState<InboxSort>(() => {
    try {
      return localStorage.getItem(SORT_KEY) === "waiting" ? "waiting" : "newest";
    } catch {
      return "newest";
    }
  });
  const [status, setStatus] = useState<ConversationStatus | "all">("open");
  const [category, setCategory] = useState(ANY);
  const [priority, setPriority] = useState(ANY);
  const [assignee, setAssignee] = useState(ANY);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);

  const filters = useMemo<ConversationFilters>(
    () => ({
      sort,
      status: status === "all" ? undefined : status,
      category: category === ANY ? undefined : category,
      priority: priority === ANY ? undefined : (priority as Priority),
      assignee: assignee === ANY ? undefined : assignee,
      q: q || undefined,
    }),
    [sort, status, category, priority, assignee, q],
  );
  const query = useConversations(filters);
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const now = useNow(30_000);

  return (
    <section
      aria-label="Conversations"
      className="flex h-full w-[22rem] shrink-0 flex-col border-r bg-card"
    >
      <header className="space-y-3 border-b p-3">
        <div className="flex items-center justify-between gap-2">
          <h1 className="flex items-center gap-2 text-base font-semibold">
            Inbox
            {query.isFetching && !query.isLoading && (
              <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Refreshing" />
            )}
          </h1>
          <div role="radiogroup" aria-label="Sort" className="flex rounded-md border p-0.5 text-[11px]">
            {SORTS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={sort === option.value}
                title={option.hint}
                onClick={() => {
                  setSort(option.value);
                  try {
                    localStorage.setItem(SORT_KEY, option.value);
                  } catch {}
                }}
                className={cn(
                  "rounded-[4px] px-2 py-0.5 text-muted-foreground",
                  sort === option.value && "bg-primary text-primary-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div role="tablist" aria-label="Status" className="grid grid-cols-4 rounded-md bg-muted p-0.5">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              role="tab"
              type="button"
              aria-selected={status === tab.value}
              onClick={() => setStatus(tab.value)}
              className={cn(
                "rounded-[5px] py-1 text-xs font-medium text-muted-foreground transition-colors",
                status === tab.value && "bg-card text-foreground shadow-xs",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, phone or email"
            aria-label="Search conversations"
            className="h-8 pl-8 text-sm"
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <FilterSelect label="Queue" value={category} onChange={setCategory}>
            <SelectItem value={ANY}>All queues</SelectItem>
            {CATEGORY_QUEUES.map((c) => (
              <SelectItem key={c.key} value={c.key}>
                {c.label}
              </SelectItem>
            ))}
          </FilterSelect>
          <FilterSelect label="Priority" value={priority} onChange={setPriority}>
            <SelectItem value={ANY}>Any priority</SelectItem>
            {(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => (
              <SelectItem key={p} value={p}>
                {PRIORITY_LABEL[p]}
              </SelectItem>
            ))}
          </FilterSelect>
          <FilterSelect label="Assignee" value={assignee} onChange={setAssignee}>
            <SelectItem value={ANY}>Anyone</SelectItem>
            <SelectItem value="me">Mine</SelectItem>
            <SelectItem value="unassigned">Unassigned</SelectItem>
          </FilterSelect>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {query.isLoading ? (
          <ListSkeleton />
        ) : query.isError ? (
          <p className="p-4 text-sm text-destructive">Could not load conversations.</p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-10 text-center text-sm text-muted-foreground">
            <Inbox className="size-6" />
            No conversations here.
          </div>
        ) : (
          <ul data-testid="conversation-list">
            {items.map((c) => (
              <li key={c.id}>
                <ConversationRow conversation={c} selected={c.id === selectedId} now={now} />
              </li>
            ))}
          </ul>
        )}
        {query.hasNextPage && (
          <div className="p-3">
            <Button
              variant="ghost"
              size="sm"
              className="w-full"
              onClick={() => query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
            >
              {query.isFetchingNextPage ? "Loading…" : "Load more"}
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

function ConversationRow({
  conversation: c,
  selected,
  now,
}: {
  conversation: ConversationListItem;
  selected: boolean;
  now: number;
}) {
  const waitingSince = c.status === "open" ? c.last_inbound_at : null;
  return (
    <Link
      href={`/inbox/${c.id}`}
      aria-current={selected ? "page" : undefined}
      data-conversation-id={c.id}
      className={cn(
        "relative block border-b px-4 py-3 transition-colors hover:bg-muted/60",
        selected && "bg-accent hover:bg-accent",
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-1", PRIORITY_STRIPE[c.priority])}
      />
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-medium">{c.customer.display_name}</span>
        {c.customer.verified && (
          <BadgeCheck className="size-3.5 shrink-0 text-primary" aria-label="Verified" />
        )}
        <span
          className="tabular ml-auto shrink-0 text-xs text-muted-foreground"
          title={waitingSince ? "Waiting for a reply" : "Last activity"}
        >
          {timeAgo(waitingSince ?? c.last_activity_at, now)}
        </span>
      </div>
      {c.last_message && (
        <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
          <ChannelIcon channel={c.last_message.channel} />
          <span className="truncate">
            {c.last_message.direction === "outbound" && (
              <span className="text-foreground/70">You: </span>
            )}
            {c.last_message.body_preview}
          </span>
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <CategoryBadge queue={c.category_queue} />
        {c.priority !== "normal" && c.priority !== "low" && <PriorityBadge priority={c.priority} />}
        {c.status !== "open" && <StatusBadge status={c.status} />}
      </div>
    </Link>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} size="sm" className="h-8 w-full text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-px">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="space-y-2 border-b px-4 py-3">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-4 w-1/4" />
        </div>
      ))}
    </div>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}
