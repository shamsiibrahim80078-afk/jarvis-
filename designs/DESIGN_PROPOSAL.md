# J.A.R.V.I.S HUD — Design Proposal (BLAST)

**Status:** APPROVED direction — blast desktop mockup implemented in `web/` (2026-09-04)  
**Implemented:** `web/index.html` + `web/css/style.css` (+ light `app.js` listening/battery hooks) matching `hud-blast-desktop.png`.  
**Still design-only:** listening-extreme / boot splash are visual inspiration; activate overlay uses boot-style reactor.

---

## Mockups (BLAST tier)

| State | File |
|--------|------|
| Full desktop HUD (standby / live) | [hud-blast-desktop.png](./hud-blast-desktop.png) |
| Listening / active | [hud-blast-listening.png](./hud-blast-listening.png) |
| Suit-up / boot splash | [hud-blast-boot.png](./hud-blast-boot.png) |

Also generated at (Cursor assets):

- `C:\Users\hp\.cursor\projects\c-Users-hp-Desktop-nexus-jarvis\assets\hud-blast-desktop.png`
- `C:\Users\hp\.cursor\projects\c-Users-hp-Desktop-nexus-jarvis\assets\hud-blast-listening.png`
- `C:\Users\hp\.cursor\projects\c-Users-hp-Desktop-nexus-jarvis\assets\hud-blast-boot.png`

Older MK-2 mockups (`hud-desktop-overview.png`, `hud-listening-active.png`, `hud-mobile-narrow.png`) are superseded for direction — keep only if you want side-by-side compare.

---

## What stays (maps to current `web/index.html`)

Same product skeleton — restyled as blockbuster HUD frames, not soft cards:

| Current region | Role |
|----------------|------|
| Top bar | Giant `J.A.R.V.I.S` brand, clock/date, connection + agent state |
| Left: RADAR + CPU/RAM/DISK/BATTERY | Telemetry with neon meters + amber alert accents |
| Center: arc-reactor core + COMMUNICATIONS + command/mic | Energy orb + chat log + EXECUTE |
| Right: MODULES, PLUGINS, QUICK ACTIONS, SCREEN SHARE | Status + shortcuts + share |
| Footer | Host, user, build tag |
| Boot / activate | Suit-up splash → first-click audio unlock |

---

## What changes (BLAST visual language)

### Vibe vs previous MK-2

| Old (rejected) | BLAST (this proposal) |
|----------------|------------------------|
| Safe corporate cyan dashboard | Movie trailer / Tony Stark workshop screens |
| Polite wireframe panels | Aggressive angular chrome + holographic depth |
| Quiet center | Arc-reactor core as the living heart of the UI |
| Flat-ish atmosphere | Particles, scan sweeps, volumetric light, bloom |
| Mild listening pulse | Waveform explosion + hot amber+cyan collision |

### Layout & composition

- **One loud composition.** Full-bleed void; panels are chrome brackets and holographic glass — never a card farm.
- **Brand is giant hero type.** `J.A.R.V.I.S` dominates the viewport; everything else supports.
- **Arc-reactor center.** Pulsing energy orb with depth layers is the visual anchor (standby calm → listening blast).
- **Real panels only.** Communications, CPU/RAM/DISK/BATTERY, modules/plugins, command+mic, screen share — styled spectacularly. No Weapon Systems / Flight fiction.
- **Listening state** is the intensity peak: concentric rings, waveform explosion, molten mic, dual cyan+amber glow.
- **Boot splash** is an extreme close-up orb / suit-up sequence before the desktop HUD.

### Color

| Token | Hex (proposed) | Use |
|-------|----------------|-----|
| Void / base | `#020508` – `#0A1218` | Deep workshop black |
| Cyan primary | `#00F0FF` | Brand, frames, reactor core, holograms |
| Cyan bloom | `#7AFFFF` | Highlights, lens flare edges |
| Amber alert | `#FFB000` – `#FF6A00` | LISTENING, warnings, hot accents |
| Online | `#00FF9C` | Module / plugin healthy dots |
| Text primary | `#E8F4F8` | Body / log |
| Text muted | `#6B8A96` | Labels, idle |

Atmosphere: volumetric shafts, particle sparks, sweep scanlines, holographic parallax — **not** purple SaaS, not cream-serif marketing, not flat single-color admin.

### Typography

- **Display / brand:** Orbitron (or equivalent) — massive weight for `J.A.R.V.I.S` and `LISTENING`.
- **UI / telemetry:** Share Tech Mono — clocks, meters, module labels, timestamps.
- Avoid Inter / Roboto / generic system UI look.

### Motion (implementation later)

- Continuous reactor pulse + ambient particle drift.
- Radar sweep; accelerate on listen.
- Listening: ring shockwaves, waveform burst, amber/cyan bloom on mic.
- Boot: rings assemble, brand fades through the core, then dissolve into desktop HUD.
- Scanline / light-shaft drift for “alive” atmosphere.

---

## Explicit non-goals (this proposal)

- No Human View / Instagram particle face work.
- No fake Iron Man combat modules (weapons, flight, targeting fiction).
- No Pepper Potts / fanfic chat copy.
- No production `web/` or `jarvis/` edits until you approve.

---

## Decision needed

**Approve this BLAST direction, or list changes** (more amber, denser chrome, softer standby, different boot, drop boot, etc.). Implementation starts only after that.
