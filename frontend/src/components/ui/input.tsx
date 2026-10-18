import * as React from "react";
import { cn } from "@/lib/utils";

const base =
  "w-full rounded-[10px] bg-white border border-[rgba(43,41,109,0.12)] text-navy placeholder:text-[rgba(43,41,109,0.4)] " +
  "px-3 font-body-md text-body-md outline-none transition-shadow " +
  "focus:border-primary-container focus:shadow-[0_0_0_4px_rgba(43,185,155,0.15)] " +
  "aria-[invalid=true]:border-tertiary aria-[invalid=true]:shadow-[0_0_0_3px_rgba(184,11,96,0.15)]";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(base, "h-11", className)} {...props} />,
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn(base, "py-2 min-h-24", className)} {...props} />,
);
Textarea.displayName = "Textarea";
