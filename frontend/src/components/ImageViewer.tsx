import { useEffect, useRef, useState } from "react";
import { TransformComponent, TransformWrapper, type ReactZoomPanPinchRef } from "react-zoom-pan-pinch";
import type { FieldName, Level } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

export interface FieldBox {
  name: FieldName;
  label: string;
  box: [number, number, number, number];
  level: Level;
  confidence: number;
  /** Tightened on a zoomed crop that read the same value; otherwise the model's rough placement. */
  verified?: boolean;
}

interface Props {
  src: string;
  title: string;
  subtitle: string;
  boxes: FieldBox[];
  /** Field to emphasise (the one being edited / hovered in the table). */
  highlight: FieldName | null;
  /** Field the user is editing: the viewer pans/zooms to it. */
  focused: FieldName | null;
  onJumpToAlert: (() => void) | null;
  footer?: string;
  /** Every page of a form merged from several pages, `src` first. The field frames belong to the first. */
  pages?: string[];
}

function Icon({ name, className = "" }: { name: string; className?: string }) {
  return <span className={`material-symbols-outlined ${className}`}>{name}</span>;
}

const toolBtn =
  "w-8 h-8 rounded flex items-center justify-center text-on-surface hover:bg-surface-container transition-colors";

/** Scanned form with zoom / rotate and a frame around every field the model found; the active one is emphasised. */
export function ImageViewer({ src, title, subtitle, boxes, highlight, focused, onJumpToAlert, footer, pages }: Props) {
  const { dir, t } = useI18n();
  const [rotation, setRotation] = useState(0);
  const [page, setPage] = useState(0);
  const wrapper = useRef<ReactZoomPanPinchRef | null>(null);
  useEffect(() => setPage(0), [src]);
  const allPages = pages && pages.length > 1 ? pages : [src];
  const shown = allPages[Math.min(page, allPages.length - 1)];
  const frames = page === 0 ? boxes : [];

  useEffect(() => {
    if (!focused) return;
    const t = window.setTimeout(() => {
      const el = document.getElementById(`field-box-${focused}`);
      if (el && wrapper.current) wrapper.current.zoomToElement(el, Math.max(wrapper.current.state.scale, 1.4), 250);
    }, 30);
    return () => window.clearTimeout(t);
  }, [focused, src]);

  // editing a field brings back the page its frame is on
  useEffect(() => {
    if (focused) setPage(0);
  }, [focused]);

  return (
    <div className="lg:col-span-6 flex flex-col gap-space-sm order-1 lg:order-1">
      <TransformWrapper
        key={shown}
        ref={wrapper}
        minScale={0.5}
        maxScale={8}
        centerOnInit
        doubleClick={{ disabled: true }}
      >
        {({ zoomIn, zoomOut, resetTransform }) => (
          <>
            <div className="bg-surface-container-lowest rounded-xl p-3 shadow-md flex items-center justify-between gap-space-sm">
              <div className="flex items-center gap-space-sm min-w-0">
                <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                  <Icon name="document_scanner" className="text-[20px]" />
                </div>
                <div className="min-w-0">
                  <span className="font-headline-sm text-headline-sm text-on-surface block leading-tight font-bold truncate">
                    {title}
                  </span>
                  <span className="font-data-mono-sm text-data-mono-sm text-on-surface-variant">{subtitle}</span>
                </div>
              </div>
              <div className="flex items-center gap-1 bg-surface-container-low p-1 rounded-lg shrink-0">
                {allPages.length > 1 && (
                  <>
                    <button
                      className={cn(toolBtn, "disabled:opacity-30")}
                      title={t("review.prevPage")}
                      type="button"
                      disabled={page === 0}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      <Icon name={dir === "rtl" ? "chevron_right" : "chevron_left"} className="text-[18px]" />
                    </button>
                    <span className="font-data-mono-sm text-data-mono-sm px-1 whitespace-nowrap">
                      {t("review.pageOf", { page: page + 1, total: allPages.length })}
                    </span>
                    <button
                      className={cn(toolBtn, "disabled:opacity-30")}
                      title={t("review.nextPage")}
                      type="button"
                      disabled={page >= allPages.length - 1}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      <Icon name={dir === "rtl" ? "chevron_left" : "chevron_right"} className="text-[18px]" />
                    </button>
                    <span className="w-[1px] h-4 bg-outline-variant/40 mx-0.5"></span>
                  </>
                )}
                <button className={toolBtn} title={t("viewer.zoomIn")} type="button" onClick={() => zoomIn()}>
                  <Icon name="zoom_in" className="text-[18px]" />
                </button>
                <button className={toolBtn} title={t("viewer.zoomOut")} type="button" onClick={() => zoomOut()}>
                  <Icon name="zoom_out" className="text-[18px]" />
                </button>
                <span className="w-[1px] h-4 bg-outline-variant/40 mx-0.5"></span>
                <button
                  className={toolBtn}
                  title={t("viewer.fit")}
                  type="button"
                  onClick={() => {
                    setRotation(0);
                    resetTransform();
                  }}
                >
                  <Icon name="fit_screen" className="text-[18px]" />
                </button>
                <button
                  className={toolBtn}
                  title={t("viewer.rotate")}
                  type="button"
                  onClick={() => setRotation((r) => r + 90)}
                >
                  <Icon name="rotate_right" className="text-[18px]" />
                </button>
                {onJumpToAlert && (
                  <button
                    className="px-2.5 h-8 rounded flex items-center gap-1 bg-tertiary-container/30 text-on-tertiary-container hover:bg-tertiary-container/50 font-label-sm text-label-sm font-bold transition-colors"
                    title={t("viewer.jumpTitle")}
                    type="button"
                    onClick={onJumpToAlert}
                  >
                    <Icon name="pin_drop" className="text-[16px]" />
                    <span>{t("viewer.jump")}</span>
                  </button>
                )}
              </div>
            </div>

            <div className="relative bg-surface-container-lowest rounded-[20px] shadow-lg overflow-hidden border border-outline-variant/30 h-[760px] flex flex-col select-none">
              <div className="absolute inset-0 bg-gradient-to-b from-amber-50/10 via-white to-slate-50/30 pointer-events-none"></div>
              <div className="relative min-h-0 flex-1 bg-surface-container-low/60" dir="ltr">
                <TransformComponent wrapperStyle={{ width: "100%", height: "100%" }}>
                  <div
                    className="relative inline-block transition-transform"
                    style={{ transform: `rotate(${rotation}deg)` }}
                  >
                    <img
                      src={shown}
                      alt={t("viewer.imageAlt")}
                      className="block max-h-[720px] max-w-full w-auto h-auto"
                      draggable={false}
                    />
                    {frames.map((b) => {
                      const [x0, y0, x1, y1] = b.box;
                      const review = b.level === "review";
                      const on = highlight === b.name;
                      const dim = highlight !== null && !on;
                      const rough = b.verified === false;
                      // Outline only, drawn just outside the value (3px of air) so the frame never covers the text.
                      return (
                        <div
                          key={b.name}
                          id={`field-box-${b.name}`}
                          className={cn(
                            "absolute rounded-md pointer-events-none transition-all duration-200 border-2 bg-transparent",
                            review ? "border-tertiary" : "border-primary-container",
                            rough && "border-dashed",
                            on &&
                              (review
                                ? "z-20 border-[3px] shadow-[0_0_0_3px_rgba(184,11,96,0.25)]"
                                : "z-20 border-[3px] shadow-[0_0_0_3px_rgba(43,185,155,0.3)]"),
                            dim && "opacity-30",
                          )}
                          style={{
                            left: `calc(${x0 * 100}% - 3px)`,
                            top: `calc(${y0 * 100}% - 3px)`,
                            width: `calc(${(x1 - x0) * 100}% + 6px)`,
                            height: `calc(${(y1 - y0) * 100}% + 6px)`,
                          }}
                        >
                          {on && (
                            <span
                              className={cn(
                                dir === "rtl" ? "right-0" : "left-0",
                                "absolute bottom-full mb-1 text-on-primary text-[10px] px-1.5 py-0.5 rounded flex items-center gap-0.5 font-bold shadow-sm whitespace-nowrap",
                                review ? "bg-tertiary" : "bg-primary",
                              )}
                              dir={dir}
                            >
                              <Icon name={review ? "error" : "check"} className="text-[12px]" />
                              {b.label} {(b.confidence * 100).toFixed(1)}%{rough ? ` · ${t("viewer.approx")}` : ""}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </TransformComponent>
              </div>
              {footer && (
                <div className="relative mt-auto px-6 py-3 flex items-center justify-between text-outline/70 font-data-mono-sm text-data-mono-sm">
                  <span>{footer}</span>
                </div>
              )}
            </div>
          </>
        )}
      </TransformWrapper>
    </div>
  );
}
