---
name: Clinical Mint & Deep Navy RTL Utility
colors:
  surface: '#f8f9fc'
  surface-dim: '#d9dadd'
  surface-bright: '#f8f9fc'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3f6'
  surface-container: '#edeef1'
  surface-container-high: '#e7e8eb'
  surface-container-highest: '#e1e2e5'
  on-surface: '#191c1e'
  on-surface-variant: '#3c4a45'
  inverse-surface: '#2e3133'
  inverse-on-surface: '#f0f1f4'
  outline: '#6c7a75'
  outline-variant: '#bbcac3'
  surface-tint: '#006b58'
  primary: '#006b58'
  on-primary: '#ffffff'
  primary-container: '#2bb99b'
  on-primary-container: '#004336'
  inverse-primary: '#59dcbc'
  secondary: '#58579d'
  on-secondary: '#ffffff'
  secondary-container: '#b3b1fe'
  on-secondary-container: '#424186'
  tertiary: '#b80b60'
  on-tertiary: '#ffffff'
  tertiary-container: '#ff78a6'
  on-tertiary-container: '#78003c'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#78f8d7'
  primary-fixed-dim: '#59dcbc'
  on-primary-fixed: '#002019'
  on-primary-fixed-variant: '#005142'
  secondary-fixed: '#e2dfff'
  secondary-fixed-dim: '#c3c1ff'
  on-secondary-fixed: '#130e56'
  on-secondary-fixed-variant: '#403f83'
  tertiary-fixed: '#ffd9e2'
  tertiary-fixed-dim: '#ffb1c7'
  on-tertiary-fixed: '#3f001c'
  on-tertiary-fixed-variant: '#8e0048'
  background: '#f8f9fc'
  on-background: '#191c1e'
  surface-variant: '#e1e2e5'
typography:
  display-lg:
    fontFamily: Heebo
    fontSize: 40px
    fontWeight: '800'
    lineHeight: 48px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Heebo
    fontSize: 30px
    fontWeight: '800'
    lineHeight: 38px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Heebo
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Heebo
    fontSize: 22px
    fontWeight: '700'
    lineHeight: 30px
    letterSpacing: '0'
  headline-md:
    fontFamily: Heebo
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 28px
  headline-sm:
    fontFamily: Heebo
    fontSize: 17px
    fontWeight: '500'
    lineHeight: 24px
  body-lg:
    fontFamily: Heebo
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Heebo
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Heebo
    fontSize: 12px
    fontWeight: '300'
    lineHeight: 18px
  data-mono-lg:
    fontFamily: JetBrains Mono
    fontSize: 15px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.02em
  data-mono-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.04em
  label-md:
    fontFamily: Heebo
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
  label-sm:
    fontFamily: Heebo
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  margin: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system establishes a clinical, reassuring, and precise interface for an AI-powered document digitization tool converting physical medical referrals and scanned laboratory reports into structured spreadsheets. Built explicitly for Hebrew-speaking clinical administrators, doctors, and medical billing specialists, the interface must reduce cognitive fatigue during intensive data verification while conveying ironclad accuracy, patient data privacy, and technological mastery.

The visual direction blends **Modern Clinical Utility** with softened, human-centric enterprise polish:
- **Calm Authority:** Deep clinical navy provides structural integrity and effortless readability for dense Hebrew typography.
- **Biomedical Optimism:** Crisp mint-teal serves as the primary operational anchor, signaling health, automation speed, and modern precision.
- **Deliberate Contrast:** High-alert berry pink is restricted to anomalies, mismatched data fields, extraction warnings, and critical destructive actions to eliminate ambient visual noise.
- **RTL-Native Ergonomics:** All structural layouts, iconography orientation, progress sweeps, and navigation structures are designed natively for Right-to-Left (dir="rtl") comprehension.

## Colors

The palette balances clinical cleanliness with high-legibility contrast ratios meeting WCAG AAA compliance for critical health informatics.

- **Primary (`#2BB99B` - Mint Medical Teal):** Drives active states, upload zones, completed extraction badges, primary progress bars, and validated table rows.
- **Secondary (`#2B296D` - Deep Clinical Navy):** The structural anchor. Applied to primary headings, table headers, high-emphasis text, and dark structural containers.
- **Tertiary / Alert (`#EA3E85` - Berry Pink):** Strictly reserved for extraction validation errors, unrecognized patient ID formats, critical missing field alerts, and primary failure recovery buttons.
- **Neutral Canvas (`#F7F8FB` - Cool Slate White):** Reduces eye strain across prolonged auditing sessions compared to pure stark white.
- **Surface Elevation (`#FFFFFF` - Pure White):** Used on interactive cards, modals, and tabular extraction workspaces.
- **Borders & Dividers (`rgba(43, 41, 109, 0.08)`):** A navy-tinted hairline border maintaining subtle separation without harsh grid lines.
- **Header Gradient:** `linear-gradient(135deg, #2BB99B 0%, #2B296D 100%)` for top navigation bars and executive metric banners.

## Typography

The typographic hierarchy implements an explicit dual-engine standard optimized for bilingual Hebrew/English environments:

1. **Heebo (RTL Primary):** Handles all Hebrew navigational text, form labels, clinical notes, and interface dialogues. With open apertures and crisp geometry, Heebo remains legible even under small optical sizes (e.g., medical disclaimers). Weights 300, 400, 500, 700, and 800 are mapped rigorously to information hierarchy.
2. **JetBrains Mono (Data & Precision Layer):** Applied exclusively to tabular Excel preview outputs, Israeli ID numbers (ת.ז.), ICD-9/ICD-10 clinical diagnostic codes, timestamps, file sizes, and token limits. Numbers and English alphanumeric strings are set with `direction: ltr; unicode-bidi: embed;` inside cells to prevent punctuation flubbing and negative sign inversion in RTL containers.

## Layout & Spacing

The design system uses an RTL-mirrored 12-column fluid grid system pinned to a maximum content width of 1440px to ensure dense medical data remains in natural optical focus.

- **RTL Fluid Columns:** Columns flow from right to left. Column 1 rests at the screen's right edge; sidebar panels dock to the right by default.
- **Dual-Pane Verification Workspace:** The primary processing screen splits 50/50 on desktop (≥1024px): Scanned source document preview anchored on the right, editable Excel mapping matrix anchored on the left.
- **Breakpoints:**
  - `Desktop (≥1024px)`: 12 columns, 24px gutter, 32px margins. Dual-pane active.
  - `Tablet (768px - 1023px)`: 8 columns, 16px gutter, 24px margins. Stacked document tab view with preview/table toggle.
  - `Mobile (<768px)`: 4 columns, 12px gutter, 16px margins. Upload-focused mobile capture mode with collapsed card previews.

## Elevation & Depth

Visual hierarchy uses softly diffused, navy-tinted ambient shadows rather than harsh neutral blacks. This maintains a light, sterile, and non-distracting feel across nested document lists.

- **Base Surface:** Flat `#F7F8FB` with no shadow.
- **Primary Cards & Containers:** `#FFFFFF` background with `box-shadow: 0 10px 30px -5px rgba(43, 41, 109, 0.07);` and an ultra-fine border `1px solid rgba(43, 41, 109, 0.06)`.
- **Floating Overlays & Tooltips:** `box-shadow: 0 16px 40px -8px rgba(43, 41, 109, 0.12);` with frosted backdrop filter (`backdrop-filter: blur(12px)`).
- **Interactive Focus / Drag & Drop Target Active:** Outlined with a 2px stroke in `#2BB99B` plus an ambient glow `0 0 0 4px rgba(43, 185, 155, 0.15)`.
- **Critical Alert Elevation:** Modal containers flagged with critical extraction failures feature a subtle top border highlight in `#EA3E85` (3px solid) and `box-shadow: 0 14px 34px -6px rgba(234, 62, 133, 0.10)`.

## Shapes

The design system enforces a disciplined geometric formula balancing clinical precision with tactile softness:

- **Cards & Data Panels:** Custom curvature set uniformly to `20px` (`rounded-[20px]`). This creates distinct, approachable document containers that counter the harshness of raw clinical tabular data.
- **Buttons & Input Fields:** Curvature set to `10px` (`rounded-lg`), providing solid click targets without looking toy-like.
- **Status Chips & Pills:** Full curvature (`rounded-full` / 9999px) for scanning indicators, conversion tags, and file extension identifiers.
- **Excel Cell Grids:** Sharp inner borders (`rounded-none` or `rounded-[4px]` on focus) to mirror familiar spreadsheet software.

## Components

### Buttons
- **Primary Action (Convert / Export to Excel):** Mint `#2BB99B` fill, `#FFFFFF` text, `font-weight: 700`, `border-radius: 10px`. Hover: darken to `#249F85`. Focus ring: `rgba(43, 185, 155, 0.3)`.
- **Secondary Action (View Scanned Original / Re-scan):** Outlined with `#2B296D`, transparent fill, `#2B296D` text. Hover: subtle fill `rgba(43, 41, 109, 0.04)`.
- **Critical CTA (Discard Scan / Override Flagged Values):** Fill `#EA3E85`, `#FFFFFF` text. Used sparingly to avoid visual overstimulation.
- **RTL Icon Positioning:** Trailing action icons (e.g., arrow down, export icon) sit to the left of the Hebrew label. Leading icons (e.g., search, upload cloud) sit to the right.

### Cards & Scanning Dropzones
- **Dropzone Card:** White `#FFFFFF` surface with `border-radius: 20px`, dashed 2px border in `#2BB99B`, soft teal ambient background tint `rgba(43, 185, 155, 0.03)`, and navy-tinted soft drop shadow (`0 10px 30px -5px rgba(43, 41, 109, 0.07)`).
- **Document Status Card:** Contains patient name in Heebo bold (`#2B296D`), matched referral ID in JetBrains Mono, and real-time processing indicator.

### Input Fields & Search
- Background `#FFFFFF`, border `1px solid rgba(43, 41, 109, 0.12)`, text `#2B296D`, placeholder `rgba(43, 41, 109, 0.4)`. Text alignment defaults to `right` for Hebrew queries; flips dynamically to `left` when typing English drug names or numeric ranges.

### Checkboxes & Radios
- Square with rounded corners (4px). Unchecked: `1.5px solid rgba(43, 41, 109, 0.2)`. Checked: `#2BB99B` fill with `#FFFFFF` checkmark. Placed on the right of the descriptive Hebrew text line.

### Data Chips & Status Badges
- **Processing:** `background: rgba(43, 41, 109, 0.06); color: #2B296D;` with an animated pulse dot.
- **Converted Successfully:** `background: rgba(43, 185, 155, 0.12); color: #1E8670;`
- **Flagged / Unreadable Field:** `background: rgba(234, 62, 133, 0.12); color: #EA3E85;`

### Specialized Medical OCR & Table Viewer
- **Side-by-side Synchronized Bounding Box:** When hovering over an Excel cell containing an extracted value (e.g., Hemoglobin count "14.2"), the corresponding Hebrew medical document on the right panel highlights with a matching `#2BB99B` translucent bounding box.
- **Confidence Rating Indicators:** Each extracted table cell features a microscopic JetBrains Mono confidence score (e.g., "99.8%"). Values below 85% confidence are flagged with a tertiary `#EA3E85` dotted underline.