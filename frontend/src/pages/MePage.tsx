import { Navigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import { IntakeQueuePage } from "@/pages/IntakeQueuePage";
import { ApprovalQueuePage } from "@/pages/ApprovalQueuePage";

/** The personal area: each role gets its own work screen. */
export function MePage() {
  const { user } = useAuth();
  if (user?.role === "intake") return <IntakeQueuePage />;
  if (user?.role === "approver") return <ApprovalQueuePage />;
  return <Navigate to="/dashboard" replace />;
}
