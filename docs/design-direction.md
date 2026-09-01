# Design direction — "Permissible Error"

> Locked before any UI code is written. Every colour, face and spacing decision in `/frontend`
> derives from this document. If a component can't be traced back to a token here, it's wrong.

## The subject, pinned

**Product:** a compliance bench for Legal Metrology enforcement.
**Audience:** Controllers and Inspectors of Legal Metrology — half of them at a desk reviewing
queues, half in a market holding a phone at a shelf. Secondary: manufacturers self-checking artwork.
**The single job of the core screen:** let an officer decide, fast and defensibly, whether a
package's declarations comply — and hand them the proof.

**Where the aesthetic comes from.** Legal Metrology is the one department whose entire remit is
measurement. Its world is brass bell weights, beam balances, vernier callipers, verification stamps
struck into instrument plates, secondary standards in felt-lined cases, and above all **tolerance** —
the legally *permissible error* around a declared value. Rule 8 does not ask whether a label looks
right; it asks whether a letter is at least N millimetres tall. So the interface is built from the
vocabulary of instruments and limits, not from the vocabulary of dashboards.

---

## Tokens

### Colour — six values, one job each

| Token | Hex | Job |
|---|---|---|
| `--chassis` | `#16191C` | Instrument body. Left rail, headers, report masthead. Never the page ground. |
| `--bone` | `#F4F5F2` | Page ground. Cool lab-paper white, green-shifted — deliberately **not** cream. |
| `--seal` | `#23406B` | Seal ink. Brand, and *every* interactive affordance: buttons, links, focus ring. |
| `--brass` | `#A67C2E` | The measure. Graduations, limit lines — and status `NEEDS_REVIEW`. |
| `--patina` | `#2C6A5D` | Verdigris. Status `PASS` / compliant. |
| `--oxide` | `#A93B28` | Oxide red. Status `FAIL` / violation. |

Neutrals are tints of `--chassis`, not grey — they stay slightly blue so bone reads warm against them.
**Status is never carried by colour alone**: every status is colour + glyph + word, so it survives
colour blindness, greyscale printing and a photocopied inspection file.

### Type — three roles

- **Display — Archivo (variable).** Pushed wide (`wdth` 110–125), weights 600–700. Engineered
  signage, the silkscreen on an instrument panel. Used with restraint: page titles, the score
  reading, section eyebrows. Never for paragraphs.
- **Body — IBM Plex Sans + IBM Plex Sans Devanagari.** The EN/हिन्दी pair, from one superfamily so
  a bilingual government product stays coherent when the language toggles.
- **Data — IBM Plex Mono.** Every number: millimetres, MRP, net quantity, rule IDs, scan IDs,
  timestamps, confidences. Numerics in mono read as an instrument readout and column-align for
  scanning.

### Layout — "the rail and the bench"

A slim graphite **rail** on the left (72px collapsed / 240px expanded) carries navigation as engraved
labels, active item marked by a brass hairline. Everything else is **the bench**: bone ground, wide
gutters, content examined under good light.

The core screen — **the examination view** — is a split bench:

```
┌──────────────────────────────┬─────────────────────────────┐
│  EVIDENCE  (sticky)          │  FINDINGS LEDGER (scrolls)  │
│  ┌────────────────────────┐  │  ▸ MRP_FORMAT      FAIL     │
│  │  label photo           │  │    Rule 6(1)(e)             │
│  │   ┌──┐ ← annotation    │  │  ▸ FONT_HEIGHT_NQ  FAIL     │
│  │   └──┘   boxes         │  │    ├──────┼───┤  ruler      │
│  │      ┌────┐            │  │  ▸ CONSUMER_CARE   REVIEW   │
│  └────────────────────────┘  │  ▸ NET_QUANTITY    PASS     │
│  [front] [back] [side]       │                             │
└──────────────────────────────┴─────────────────────────────┘
```

Hovering a ledger row pulses its box on the image; hovering a box highlights its row. The link runs
both ways because an officer works in both directions — from a suspicion to the evidence, and from
something odd on the pack to what rule it breaks.

---

## Signature: **the Measure**

One idea, three applications, all of them load-bearing — never decoration.

**1. Rule 8 findings render as an actual ruler.** Not a red badge saying "font too small." A
graduated millimetre scale, a hard brass **limit line** at the legally required height, an index at
the measured height, and the shortfall shaded in oxide:

```
  0    1    2    3    4    5    6 mm
  ├─┬──┼─┬──┼─┬──┼─┬──┼─┬──┼─┬──┤
       ▓▓▓▓▓▓▓▓▌                        measured  1.4 mm
                 ┃ required 2.0 mm  (Rule 8, Table I · PDP 180 cm²)
```

The officer sees the violation *as a measurement*. This is the thing the product does that nothing
else does, so it gets the boldness budget.

**2. The compliance score is a calibrated scale reading** — linear, graduated, with a limit line at
the pass threshold and an index that settles on the value. Deliberately **not** radial: a
speedometer or donut is the template answer and breaks the ruler metaphor.

**3. The graduation tick becomes the structural rule** — uneven ticks, tall at tens, short between —
used as the section divider and as the texture on the rail. It's the same instrument, everywhere.

Everything around the Measure stays quiet: flat surfaces, no gradients, no glass, no shadow theatre,
`border-radius: 2px` (the corner of a printed form, not a pill).

## Motion — one orchestrated moment

The **scan reveal**, when results land: annotation boxes stroke-draw onto the image in sequence,
ledger rows stagger up behind them, the score index sweeps once to its reading. That's the moment.
Everywhere else motion is 120ms and purely functional — hover, focus, disclosure.
`prefers-reduced-motion` → boxes appear, index jumps, no stagger, nothing lost.

## Voice

Active, specific, from the officer's side of the screen. A button says what happens and keeps its
name through the flow: **Run compliance check** → toast **Compliance check complete**. Never "Submit."

Findings state the fact and the remedy, never apologise, never hedge into mood:

> **Net quantity numerals below required height.** Measured 1.4 mm; Rule 8 Table I requires 2.0 mm
> for a principal display panel of 180 cm². Reprint at 2 mm or larger.

Empty screens direct rather than decorate: *"No scans yet. Upload label photographs to run the first
compliance check."*

---

## Self-critique against the AI-default clusters

| Default | Avoided by |
|---|---|
| Cream `#F4F1EA` + high-contrast serif + terracotta `#D97757` | Cool bone ground, wide grotesque display, brass + seal-indigo. No serif, no clay. |
| Near-black ground + one acid accent | Graphite is chassis only; the ground is bone. Six-colour semantic palette, no acid. |
| Broadsheet hairlines + zero radius + dense columns | Hairlines exist but as *graduations* carrying scale, not newspaper rules. |
| `01 / 02 / 03` numbered markers | Used only on the case lifecycle, which is genuinely ordered. Nowhere else. |
| Donut / gauge score, badge pills, progress bars | Replaced by the linear calibrated reading — the same instrument as the Rule 8 ruler. |

**The risk, stated plainly:** swapping standard dashboard vocabulary for instrument vocabulary. It's
justified because the statute is measurement against legal limits, and the product's one novel check
is a millimetre measurement that a badge fundamentally cannot express.

## Quality floor (assumed, not announced)

Responsive to 360px · visible `--seal` focus ring on every interactive element · full keyboard paths
including the examination view · AA contrast on all text and status pairs · `prefers-reduced-motion`
honoured · EN/हिन्दी toggle with no layout break · the PDF report uses these same tokens and the same
Measure component, so screen and paper are recognisably one system.

---

# v2 amendment — "Motion & depth"

> Added after the original was locked. It **extends** the *Motion — one orchestrated moment* section
> above; it does not loosen anything in *Self-critique against the AI-default clusters*. The palette,
> the flat surfaces, `--radius: 2px`, the linear score, and colour + glyph + word are all unchanged.
>
> **Why:** most officers use MetroScan on a phone at a shelf. A field tool that feels inert is a tool
> that gets closed. The instrument metaphor already contains motion — a needle settles, a scale is
> read — so the fix is to *use the instrument's own motion*, not to bolt on product-marketing shine.
>
> **The one test for any new effect:** it represents a real quantity settling, or it moves the officer
> between two states they asked to move between. If it is neither, it does not ship.

## What is now permitted, and its ceiling

**Depth — the bench has up to three planes.** On the examination view: evidence photo at the back,
annotation boxes in the middle, the findings ledger at the front. Parallax translation between planes
is capped at **12px** and is driven only by scroll or pointer, never by a timer. No perspective is
ever applied to running text. On touch and under `prefers-reduced-motion` the planes are coplanar.

**The Measure may tilt.** A pointer-following `rotateX/rotateY` of **≤ 6°** with a critically-damped
spring back to flat. Pointer devices only — disabled on touch and under reduced motion. The
graduations, the brass limit line and the numerals never skew, scale or distort; only the plane they
sit on tips. The tilt carries no information — it is the feel of a physical rule under a desk lamp,
nothing more.

**Route transitions are a shared-axis move.** ≤ **240ms**, a slide-plus-fade along the direction of
navigation, easing `cubic-bezier(0.2, 0, 0.2, 1)` (the existing `--tick` curve). Back is the mirror
of forward. Under reduced motion it is a cross-fade with no translation.

**Data draws itself once.** Bars, the score scale, the Rule 8 rule and every dashboard chart animate
from empty to their value **on first enter only**, stagger ≤ **40ms** per item. They never re-animate
on hover, never loop, never pulse for attention. A value that changes later (a re-run moves the
verdict) tweens to its new position over one `--tick`.

**The scan reveal is the one big moment** (unchanged in intent, now fully specified): annotation boxes
stroke-draw in reading order, ledger rows stagger up a beat behind each box, the score index sweeps
once and settles with a single small overshoot. One timeline, one hook (`useScanReveal`). Reduced
motion: boxes appear, rows appear, index jumps — same information, no choreography.

## Still forbidden (reaffirmed)

Gradients as decoration · glassmorphism / blur panels · stacked drop shadows (the one `--lift`
hairline stands) · any animation that runs without a user action or a scroll · looping or "breathing"
ambient motion · parallax on body copy · a donut, gauge, radial or speedometer anything · motion that
conveys information a static reading doesn't already carry · effects that cost a frame budget on a
mid-range Android.

## Enforcement

Every new animation cites the clause above that admits it, in a comment. A dev-only overlay
(future work) flags any transition that fired without a preceding user event or scroll. If a screen
starts to feel like a landing page, that is the signal to stop and cut back, not to tune it.
