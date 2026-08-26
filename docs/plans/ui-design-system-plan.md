# UI & Interface Design System Plan

Status: PROPOSED v1
Owner: operator
Applies to: all user-facing surfaces in this ecosystem - venus assistant,
riley-studio, deskmate cards, any future woven front-ends.

## 1. Principles (the five laws)

1. **Content-first darkness.** The interface is achromatic near-black;
   content supplies every drop of color. Chrome recedes, media glows.
2. **Deference.** Controls support the work; they never compete with it.
   If an element does not help the user act or understand, it shrinks or
   disappears.
3. **Clarity.** Legible at every size, precise icons, obvious function.
   A control that must be explained has already failed.
4. **Depth over decoration.** Hierarchy comes from layering, elevation,
   and motion - never from ornament.
5. **One voice, everywhere.** Identical tokens across every surface and
   platform we ship; a button here and a button there share DNA.

## 2. Token foundation (single source of truth)

All values live in one tokens file per app, generated from a shared spec.

### Color

| Role | Token | Value |
| --- | --- | --- |
| Base canvas | `bg/base` | `#121212` |
| Elevated surface | `bg/elevated` | `#181818` |
| Controls/inputs | `bg/control` | `#1f1f1f` |
| Primary text | `fg/primary` | `#ffffff` |
| Secondary text | `fg/secondary` | `#b3b3b3` |
| Muted/meta | `fg/muted` | `#696969` |
| Accent (functional ONLY) | `accent` | `#1ed760` |
| Danger | `semantic/negative` | `#f3727f` |
| Warning | `semantic/warning` | `#ffa42b` |
| Info | `semantic/info` | `#539df5` |

Rules:

- The accent appears ONLY on play/primary actions, active states, and
  focus rings. Never decorative, never a background wash.
- Content imagery drives dynamic theming: extract a dominant color from
  media/artwork and use it solely in gradients behind that content,
  gated by a contrast check against white text (>= 4.5:1).
- Dark-first. Light mode is derived later via role remapping, never by
  inverting hexes ad hoc.

### Typography

- One family, three roles: display (titles), body (UI), mono (data).
  Fallback stack ends in system fonts for global script coverage.
- Compact scale built for density, not magazine spreads:

| Style | Size | Weight | Use |
| --- | --- | --- | --- |
| Title | 24px | 700 | page/section titles |
| Feature | 18px | 600 | card headings |
| Body bold | 16px | 700 | emphasized rows |
| Body | 16px | 400 | default |
| Caption | 14px | 400 | metadata, timestamps |
| Micro | 12px | 400 | badges only |

- Line-height tight (1.3 body, 1.1 titles); letter-spacing positive
  (+1.4px) and uppercase ONLY on button labels.

### Geometry

- Buttons: full pill (`radius: 9999px`). Play/primary media controls:
  perfect circles (50%). Cards/inputs: 4–8px.
- Minimum interactive target: **44x44 px** everywhere, including desktop.
- Spacing on a 4px base grid; layout margins 16/24px by breakpoint.

### Depth & elevation

Dark backgrounds hide soft shadows; ours are heavy by design:

- Card lift: `rgba(0,0,0,0.3) 0 8px 16px`
- Dialog/menu float: `rgba(0,0,0,0.5) 0 8px 24px`
- Recessed inputs: inset hairline `rgba(124,124,124) 0 0 0 1px`
- Hairline separators instead of borders wherever possible.

## 3. Layout & navigation patterns

- **Three-region shell** (desktop): left nav rail, scrollable content
  column, persistent context/action bar pinned bottom (the "console").
  Collapses to bottom tab bar on narrow screens - thumb-reachable.
- **Card architecture.** One card primitive builds every surface:
  square art for objects, circles for people, list rows for dense data.
  Vary shape + metadata, never structure.
- **Dense-but-browsable lists:** 44px rows, hover reveals inline actions,
  active row tinted `bg/control`, never outlined.
- **Immersive detail view:** content page floods its extracted gradient;
  controls float above it; back-path always visible.

## 4. Motion

- Durations: 150ms (micro), 250ms (panels), 400ms (immersive transitions).
- Standard easing `cubic-bezier(0.2, 0, 0, 1)`; nothing bounces.
- Motion informs (spatial relationship), focuses (attention), celebrates
  (rare milestone moments only).
- Honor reduced-motion: every transition has a fade fallback; information
  is never conveyed by motion alone.

## 5. Accessibility floor (non-negotiable)

- Contrast >= 4.5:1 body text, >= 3:1 large text/UI components -
  verified per token pair, both modes.
- Full keyboard traversal + visible focus ring (accent-colored, 2px).
- Text scales to 200% without loss of function (no fixed-height text
  containers); Dynamic-type-friendly layouts.
- Every icon-only control carries a label (tooltip + assistive name).

## 6. Implementation phases

Phase 1 - Tokens (verifiable first):
- Emit shared token spec -> per-app CSS variables/theme files.
- Acceptance: every color/font/radius in the apps resolves from tokens;
  zero raw hexes outside the tokens file. Verify: grep gate for raw hex
  outside tokens, plus visual smoke of one screen per app.

Phase 2 - Shell + primitives:
- Three-region shell, pill/circle buttons, card primitive, list rows.
- Acceptance: one full screen per surface rebuilt from primitives only;
  keyboard traversal passes; 44px targets enforced by lint/test.

Phase 3 - Dynamic theming + motion:
- Extracted-color gradients behind content with contrast gate; motion
  pass with reduced-motion fallbacks.
- Acceptance: contrast gate runs in CI on extracted palettes; motion
  audit checklist signed off.

Rollback: each phase lands behind its own commit range; reverting the
tokens file restores prior visuals byte-exact.

## 7. Workshop integration

This plan is executable through the DAEDALUS workshop:

- Blueprint `ui-shell` (daedalus/blueprint_uishell.py) weaves the
  Phase-1+2 shell as a self-proving app: dark tokens, three-region
  shell, card primitive, pill/circle geometry, 44px targets, and the
  error-contract API - all pinned by its self-test gate.
- Commission: `python -m daedalus build --blueprint ui-shell --name <slug>`
- Design-law faults (`flat_theme`, `mute_cards`, `square_buttons`)
  let @icarus prove the gate rejects violations and the repair pass
  restores canonical design without operator help.
- Token changes start here (section 2), flow into the blueprint, and
  the gate enforces them on every future weave.

## 8. Do / Don't (quick law)

Do: dark immersion; accent = function; pills and circles; heavy shadows;
content supplies color; density with breathing room.
Don't: decorative accent; light primary surfaces; square buttons; subtle
shadows on dark; extra brand hues; relaxed airy line-heights; icon-only
controls without names.
