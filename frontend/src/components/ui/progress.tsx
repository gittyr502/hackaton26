import { cn } from "@/lib/utils";

export function Progress({ value, failed }: { value: number; failed?: boolean }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface-high">
      <div
        className={cn("h-full rounded-full transition-all", failed ? "bg-danger" : "bg-primary-container")}
        style={{ width: `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%` }}
      />
    </div>
  );
}
