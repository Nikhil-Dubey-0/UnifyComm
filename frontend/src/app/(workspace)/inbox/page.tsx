import { MessagesSquare } from "lucide-react";

export default function InboxEmpty() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
      <MessagesSquare className="size-8" />
      <div>
        <p className="font-medium text-foreground">Select a conversation</p>
        <p className="text-sm">Urgent and longest-waiting customers are at the top.</p>
      </div>
    </div>
  );
}
