import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "review" | "processing" | "danger";

const tones: Record<Tone, string> = {
  neutral: "bg-[rgba(43,41,109,0.06)] text-navy",
  success: "bg-[rgba(43,185,155,0.12)] text-[#1E8670]",
  // pink is reserved for "needs a look"
  review: "bg-review text-review-ink",
  processing: "bg-[rgba(43,41,109,0.06)] text-navy",
  danger: "bg-error-container text-on-error-container",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-label-sm text-label-sm font-bold whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {tone === "processing" && <span className="w-1.5 h-1.5 rounded-full bg-navy animate-pulse" />}
      {children}
    </span>
  );
}
