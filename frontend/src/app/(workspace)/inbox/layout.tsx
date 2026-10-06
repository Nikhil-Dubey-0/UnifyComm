import { ConversationList } from "@/components/inbox/conversation-list";

export default function InboxLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full">
      <ConversationList />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
