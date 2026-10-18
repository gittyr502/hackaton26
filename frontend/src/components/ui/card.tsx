import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** White 20px card with the navy-tinted ambient shadow from DESIGN.MD. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-surface-container-lowest rounded-[20px] border border-[rgba(43,41,109,0.06)] shadow-[0_10px_30px_-5px_rgba(43,41,109,0.07)]",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  hint,
  icon,
  action,
}: {
  title: ReactNode;
  hint?: ReactNode;
  icon?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-space-sm px-space-lg pt-space-lg pb-space-sm">
      <div className="flex items-center gap-space-sm min-w-0">
        {icon && (
          <div className="w-9 h-9 rounded-lg bg-secondary/10 text-secondary flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-[20px]">{icon}</span>
          </div>
        )}
        <div className="min-w-0">
          <h2 className="font-headline-sm text-headline-sm font-bold text-navy leading-tight">{title}</h2>
          {hint && <p className="font-body-sm text-body-sm text-on-surface-variant">{hint}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

/** A KPI tile: icon, label and a big number. `accent` uses the "needs a look" pink. */
export function Kpi({ label, value, icon, accent }: { label: string; value: string | number; icon: string; accent?: boolean }) {
  return (
    <Card className="p-space-md flex items-center gap-space-md">
      <span
        className={
          "w-11 h-11 rounded-xl flex items-center justify-center shrink-0 " +
          (accent ? "bg-review text-review-ink" : "bg-primary-container/15 text-primary")
        }
      >
        <span className="material-symbols-outlined text-[24px]">{icon}</span>
      </span>
      <div className="min-w-0">
        <div className="font-label-md text-label-md text-on-surface-variant truncate">{label}</div>
        <div className="font-headline-lg text-headline-lg font-bold text-navy font-data-mono-lg" dir="ltr">
          {value}
        </div>
      </div>
    </Card>
  );
}
