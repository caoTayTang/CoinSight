---
name: CoinSight Editorial
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#3e4947'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#6e7977'
  outline-variant: '#bdc9c6'
  surface-tint: '#006a63'
  primary: '#005c55'
  on-primary: '#ffffff'
  primary-container: '#0f766e'
  on-primary-container: '#a3faef'
  inverse-primary: '#80d5cb'
  secondary: '#455f87'
  on-secondary: '#ffffff'
  secondary-container: '#b5d0fd'
  on-secondary-container: '#3e5980'
  tertiary: '#56504c'
  on-tertiary: '#ffffff'
  tertiary-container: '#6f6863'
  on-tertiary-container: '#f2e8e2'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#9cf2e8'
  primary-fixed-dim: '#80d5cb'
  on-primary-fixed: '#00201d'
  on-primary-fixed-variant: '#00504a'
  secondary-fixed: '#d5e3ff'
  secondary-fixed-dim: '#adc8f5'
  on-secondary-fixed: '#001c3b'
  on-secondary-fixed-variant: '#2d486d'
  tertiary-fixed: '#eae1da'
  tertiary-fixed-dim: '#cec5bf'
  on-tertiary-fixed: '#1f1b17'
  on-tertiary-fixed-variant: '#4b4641'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  display-lg:
    fontFamily: Newsreader
    fontSize: 40px
    fontWeight: '400'
    lineHeight: 48px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Newsreader
    fontSize: 32px
    fontWeight: '400'
    lineHeight: 40px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Newsreader
    fontSize: 28px
    fontWeight: '400'
    lineHeight: 36px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Newsreader
    fontSize: 22px
    fontWeight: '500'
    lineHeight: 30px
    letterSpacing: -0.005em
  title-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
    letterSpacing: -0.01em
  title-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: 0em
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
    letterSpacing: 0em
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  number-editorial:
    fontFamily: Newsreader
    fontSize: 30px
    fontWeight: '400'
    lineHeight: 36px
    letterSpacing: -0.01em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 3rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.75rem
  space-xl: 2.5rem
---

## Brand & Style

CoinSight Editorial represents an intentional departure from the hyper-gamified, neon-soaked, anxiety-inducing aesthetics typical of cryptocurrency and retail finance platforms. The product positions itself as a calm, contemplative financial intelligence companion for thoughtful investors, analysts, and wealth stewards who value clarity, signal over noise, and editorial depth over adrenaline.

The aesthetic philosophy merges **Modern Editorial Publishing** with **Warm Minimalist Utility**:
- **Tone**: Measured, literate, objective, and deeply human-centered. Information is treated with the rigor of high-end journalism and the quiet efficiency of an archival tool.
- **Atmosphere**: Serene and deliberate. Surfaces are cast in warm slate and paper-like neutrals, leaving ample breathing room around complex data.
- **Visual Restraint**: Zero terminal glows, zero skeuomorphic chrome, zero aggressive badge capitalization, and zero ticker-tape frenzy. The platform invites long-form reading, thoughtful portfolio synthesis, and deliberate decision-making.

## Colors

The palette is engineered around organic, grounded pigments that invoke ink on archival stock rather than pixels on a monitor.

### Key Tokens & Usage
- **Primary (`#0f766e` - Deep Petrol Teal)**: Acts as the primary anchor for interactive focus states, primary brand actions, selected navigational anchors, and authoritative data series. It projects stability, depth, and intelligence without digital harshness.
- **Secondary (`#1e3a5f` - Quiet Indigo Slate)**: Used for deep structural accents, secondary interactive affordances, key metric callouts, and multi-asset comparative charting.
- **Tertiary (`#78716c` - Muted Stone)**: Handles neutral metadata, secondary annotations, timestamp indicators, and subtle divider contexts.
- **Neutral Surface (`#f8f9fa` transitioning to `#f4f5f6` and `#ffffff`)**: A bespoke warm off-white and chalk-slate range. Pure white (`#ffffff`) is reserved strictly for elevated reading cards and active data panels to establish clean hierarchy against the base canvas (`#f8f9fa`).

### Specialized Semantic Rules
- **Price Delta Strictness**: Directional green (`#15803d`) and red (`#b91c1c`) are deployed strictly and exclusively for signed financial movements (`+X.XX%`, `-X.XX%`). They never appear as large button backgrounds, full-card fills, or decorative glows.
- **Text & Ink**: Primary body text is set in deeply pigmented charcoal ink (`#1c1917`), avoiding pure digital black to preserve warmth. Secondary copy resolves to stone slate (`#57534e`).

## Typography

The typographic system pairs the literary authority of **Newsreader** (an editorial serif with organic warmth) with the clean, balanced humanist geometry of **Plus Jakarta Sans**.

- **Editorial Headlines & Numbers**: Major market intelligence briefs, long-form titles, and primary portfolio balances leverage Newsreader. Its literary presence communicates durability and measured perspective. Numerical values in portfolio overviews use Newsreader's proportional or tabular figures for an elevated financial-journal quality.
- **Interface & Analytical Copy**: Plus Jakarta Sans drives application ergonomics, dense data tables, interactive controls, and explanatory paragraphs. Its open apertures ensure effortless legibility even in small analytical callouts.
- **Casing & Pacing Rules**: Avoid uppercase shouting or acronym badge culture. Labels, metrics, and categories use sentence casing (e.g., "Market capitalization" instead of "MARKET CAP").

## Layout & Spacing

CoinSight Editorial uses a structured, generous column framework prioritizing reading rhythm and analytical clarity.

- **Desktop (1200px+)**: 12-column responsive grid with a comfortable max-width reading container (`1280px`). Gutters are set to `1.5rem` and outer margins to `3rem` to maintain an airy, publication-like margin.
- **Tablet (768px - 1199px)**: 8-column layout with `1.25rem` gutters and `2rem` outer margins. Secondary analysis sidebars reflow below primary telemetry modules.
- **Mobile (< 768px)**: 4-column layout with `1rem` gutters and `1.25rem` canvas margins. Stack order prioritizes the primary thesis/editorial digest before secondary metrics.
- **Spatial Rhythm**: The layout leans toward deliberate whitespace. Generous vertical gaps (`space-xl` or `2.5rem`) separate distinct intellectual concepts, preventing visual fatigue and encouraging systematic comprehension.

## Elevation & Depth

Visual hierarchy is maintained via low-contrast tonal layering and ultra-quiet hairline boundaries rather than dramatic physical drop-shadows or high-contrast dropouts.

- **Canvas Foundation**: The backdrop sits at `#f8f9fa` (a warm, soft slate paper).
- **Surface Elevation**: Primary cards, reading modules, and analytical dashboards sit at `#ffffff`. They are distinguished from the canvas using a continuous, gossamer hairline border (`1px solid #e7e5e4`) accompanied by an ultra-diffused, ambient whisper shadow:
  - `box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03), 0 6px 16px -4px rgba(15, 23, 42, 0.02);`
- **Floating Overlays & Modals**: Menus, context overlays, and deep-dive panels use a slightly stronger yet softened boundary (`1px solid #d6d3d1`) with a restrained elevation:
  - `box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.06);`
- **Zero Glare**: Luminance blurs, skeuomorphic bevels, and vivid edge-lit glows are strictly avoided. Depth remains quiet, tactile, and naturalistic.

## Shapes

The design system embraces a **Soft (Level 1)** geometric posture, reinforcing architectural order and quiet editorial sophistication.

- **Base Radius (`0.25rem` / 4px)**: Applied to input elements, tiny tags, pill indicators, and table cell focus rings.
- **Card & Modular Radius (`rounded-lg` / `0.5rem` / 8px)**: Governs informational cards, analytical viewports, dialogs, and modular panels.
- **Container Radius (`rounded-xl` / `0.75rem` / 12px)**: Used exclusively for major canvas section blocks or prominent slide-over sheets.

This restrained corner rounding avoids playful bubble-like geometries, anchoring the interface in a serious, crafted aesthetic reminiscent of quality bookbinding and contemporary print layout.

## Components

### Buttons
- **Primary**: Solid deep petrol teal background (`#0f766e`) with clean white text (`#ffffff`), `0.25rem` border radius, and `space-sm` vertical by `space-md` horizontal padding. Hover shifts smoothly to `#115e59`.
- **Secondary / Outline**: Clean white background (`#ffffff`), faint border (`1px solid #d6d3d1`), and charcoal text (`#1c1917`). Hover initiates an ultra-subtle tint (`#f5f5f4`).
- **Ghost / Text**: Transparent background, slate ink (`#44403c`), with subtle underline or color transition to petrol teal on hover.

### Cards & Modules
- Structured on `#ffffff` surfaces with a crisp `1px solid #e7e5e4` perimeter.
- Generous internal padding (`space-lg`). Content sections within a card are partitioned with delicate hairline dividers (`1px solid #f0eeeb`) rather than heavy background alternations.

### Input Fields & Controls
- **Inputs**: Crisp white surface, soft border (`1px solid #d6d3d1`), standard padding (`0.625rem 0.875rem`), text in `#1c1917`. Focus is distinguished cleanly by a `1px solid #0f766e` border and a faint petrol tint ring (`0 0 0 3px rgba(15, 118, 110, 0.08)`).
- **Checkboxes & Radios**: Minimalist boxes with `1px solid #a8a29e` borders. Checked state fills with `#0f766e` with an unadorned white mark.

### Data Tables & Lists
- Table headers use `label-sm` in stone slate (`#78716c`), flush left or numerical flush right, with a delicate border bottom (`1px solid #e7e5e4`).
- Rows feature generous breathing room (`space-md` height), faint divider lines, and an ultra-soft hover state (`#f5f5f4`). No zebra striping.

### Delta Chips & Status Indicators
- Subtle, subdued pills. Positive price deltas use a quiet soft-green background tint (`rgba(21, 128, 61, 0.08)`) with dark forest text (`#15803d`). Negative deltas use a soft-red background tint (`rgba(185, 28, 28, 0.08)`) with deep crimson text (`#b91c1c`).
- Glyphs are unpretentious standard arrows (`↑`, `↓`) or plain signs (`+`, `−`).

### Editorial Callouts
- Highlighted intelligence perspectives use a wide left-edge rule (`2px solid #0f766e`), set over a faint surface tint (`#f4f6f6`) with Newsreader body text, providing readers with seamless contextual analysis alongside market data.