---
version: alpha
name: Knos
description: The Knos web tokens (web/brand/tokens.css) for the NEAR pages and the IRIS dashboard. Dark first, a light theme by preference.
colors:
  primary: "#93a5ff"
  on-primary: "#07080c"
  neutral: "#07080c"
  surface: "#0f1118"
  soft: "#151822"
  ink: "#e9ebef"
  ink-2: "#a0a7b8"
  line: "#222634"
  ok: "#5fd28f"
  bad: "#ff8a80"
  warn: "#e0b354"
  light-primary: "#2b3bb5"
  light-on-primary: "#ffffff"
  light-neutral: "#f4f4f0"
  light-surface: "#ffffff"
  light-soft: "#eaeae4"
  light-ink: "#15171c"
  light-ink-2: "#555b68"
  light-line: "#dcdcd4"
  light-ok: "#17703f"
  light-bad: "#b3261e"
  light-warn: "#8a6100"
typography:
  display:
    fontFamily: Bricolage Grotesque
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: -0.025em
  headline:
    fontFamily: Bricolage Grotesque
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -0.015em
  title:
    fontFamily: Bricolage Grotesque
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: -0.015em
  body:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.4
  fine:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.4
  mono:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: '"tnum" 1'
rounded:
  sm: 8px
  md: 14px
  card: 18px
  full: 999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 40px
  gutter: 16px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: 44px
  button-quiet:
    backgroundColor: transparent
    textColor: "{colors.ink}"
    borderColor: "{colors.line}"
    rounded: "{rounded.md}"
    height: 44px
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.line}"
    rounded: "{rounded.card}"
  chip:
    borderColor: "{colors.line}"
    rounded: "{rounded.full}"
    typography: "{typography.label}"
---

# Knos

## Overview

Plain and exact: a ledger you can trust, not a show. Dark first; the light theme follows the reader's setting. Numbers lead, sentences follow. The first two words of every line carry its meaning. One accent colour (periwinkle on dark, deep indigo on light) marks the one thing to press. No glow, no neumorphism, no gradients behind text.

## Colors

- **Primary (#93a5ff, light #2b3bb5):** the one action and the link underline. Never a fill behind body text.
- **Neutral (#07080c, light #f4f4f0):** the page.
- **Surface (#0f1118, light #ffffff):** cards and tables.
- **Ink (#e9ebef, light #15171c) and Ink 2 (#a0a7b8, light #555b68):** text and secondary text.
- **Ok, Bad, Warn:** state, always with a word or a mark next to it: colour is never the only signal.

## Typography

Bricolage Grotesque for headings, Geist for text, JetBrains Mono with tabular figures for amounts, hashes and ids. Self-hosted woff2 with `font-display: optional`.

## Layout

A 1200px column with a 16px gutter on phones; content blocks at 65 characters. Spacing steps 4, 8, 12, 16, 24 and 40px. Every target at least 44px. No horizontal scroll at 390px.

## Elevation & Depth

One light, above and a little to the left: a 1px top highlight and a soft shadow below (`--depth-1` to `--depth-3` in tokens.css). Cards lift 2px on hover or keyboard focus.

## Shapes

Radii 8px for small controls, 14px for buttons and inputs, 18px for cards, round for chips.

## Components

Buttons (primary filled, quiet outlined), cards, chips, tables with tabular figures, a status line with a spinner that stops under reduced motion, a toast that says what just happened.

## Motion

Durations 120ms (state), 240ms (enter), 480ms (a story beat); easing `cubic-bezier(.2,.8,.2,1)`. Motion shows how a state was reached; the state is drawn first. Under `prefers-reduced-motion: reduce` nothing moves longer than 150ms and the story page shows a still poster with the same labels.

## Do's and Don'ts

- Do show the measured number and its source; never an estimate.
- Do label test money as test money on every page that shows an amount.
- Don't use colour alone for state, sound, glow, or more than one accent.
- Don't ship text that compares Knos to a marketplace.
