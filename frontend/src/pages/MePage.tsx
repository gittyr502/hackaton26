import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import { IntakeQueuePage } from "@/pages/IntakeQueuePage";
import { ApprovalQueuePage } from "@/pages/ApprovalQueuePage";
import { hasRole, roleLabel } from "@/lib/labels";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

type QueueRole = "intake" | "approver";

/** The personal area: each role gets its own work screen; someone with both picks between them. */
export function MePage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const queues = (["intake", "approver"] as QueueRole[]).filter((r) => hasRole(user, r));
  const [current, setCurrent] = useState<QueueRole | null>(null);
  if (!queues.length) return <Navigate to={hasRole(user, "lab_manager") ? "/dashboard" : "/admin/users"} replace />;
  const shown = current && queues.includes(current) ? current : queues[0];
  return (
    <>
      {queues.length > 1 && (
        <div className="w-full px-margin pt-space-md">
          <div className="max-w-[1440px] mx-auto flex items-center gap-1 bg-surface-container rounded-xl p-1 w-fit">
            {queues.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setCurrent(r)}
                className={cn(
                  "px-4 py-1.5 rounded-lg font-label-md text-label-md transition-all",
                  r === shown ? "bg-surface-container-lowest font-bold shadow-sm" : "text-on-surface-variant",
                )}
              >
                {roleLabel(t, r)}
              </button>
            ))}
          </div>
        </div>
      )}
      {shown === "intake" ? <IntakeQueuePage /> : <ApprovalQueuePage />}
    </>
  );
}
