import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "outline" | "ghost" | "destructive";
type Size = "default" | "sm" | "icon";

const variants: Record<Variant, string> = {
  default: "bg-primary-container text-white shadow-md hover:bg-[#249f85] hover:shadow-lg",
  outline: "bg-white text-secondary shadow-sm ring-1 ring-outline-variant hover:bg-secondary/5",
  ghost: "text-ink-variant hover:bg-surface-container",
  destructive: "bg-danger text-white hover:bg-red-800",
};
const sizes: Record<Size, string> = {
  default: "h-10 px-5 text-sm",
  sm: "h-8 px-3 text-xs",
  icon: "h-8 w-8",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[10px] font-bold transition-all active:scale-95",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        "disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
