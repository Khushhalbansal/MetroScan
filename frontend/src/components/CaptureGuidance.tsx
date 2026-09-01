/*
  How to photograph a pack, as the instruction plate on an instrument rather than an
  onboarding carousel.

  A verification office keeps a printed card beside the bench showing correct placement.
  That is the form this takes: four technical plates, each stating the right setup and
  the wrong one beside it, with the consequence named in the officer's terms — not
  "tip: hold steady!" but "type measures shorter than it is".

  These are illustrations and nothing else. They are static SVGs served from the web
  root; they are never uploaded, never stored as evidence, and there is no code path
  from this component to the scan pipeline. A scan's evidence lives behind
  /api/v1/scans/{id}/images/{id} and is fetched with an auth header — a different
  origin path, a different fetch, a different lifetime.
*/

import { useState } from "react";

import "./CaptureGuidance.css";

interface Plate {
  src: string;
  heading: string;
  because: string;
}

const PLATES: Plate[] = [
  {
    src: "/guidance/01-lay-the-pack-flat.svg",
    heading: "Look straight down at the panel",
    because:
      "A panel photographed at an angle is foreshortened, so its type measures shorter " +
      "than it is — and a compliant pack can be recorded as failing Rule 8.",
  },
  {
    src: "/guidance/02-scale-card-in-frame.svg",
    heading: "Put something of known size in the frame",
    because:
      "A photograph carries no scale of its own. Without a reference, character heights " +
      "cannot be recovered at all and every Rule 8 finding comes back for review.",
  },
  {
    src: "/guidance/03-declaration-panel-facing.svg",
    heading: "Photograph the panel with the declarations",
    because:
      "The front of a pack usually carries branding, not declarations. A scan that only " +
      "sees the brand face cannot tell you whether the mandatory declarations are there.",
  },
  {
    src: "/guidance/04-even-light-no-glare.svg",
    heading: "Light the pack from the side",
    because:
      "Light bouncing straight back into the lens blows out a patch of the panel. " +
      "Whatever was printed under it reads as nothing at all.",
  },
];

export function CaptureGuidance() {
  const [open, setOpen] = useState(false);

  return (
    <section className="plate-set">
      <button
        type="button"
        className="plate-set__toggle"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        <span className="plate-set__toggle-label eyebrow">
          How to photograph a pack
        </span>
        <span className="plate-set__toggle-state" aria-hidden="true">
          {open ? "Hide" : "Show"} the four plates
        </span>
      </button>

      {open && (
        <>
          <div className="graduated" aria-hidden="true" />
          <ul className="plates">
            {PLATES.map((plate) => (
              <li key={plate.src} className="plate">
                {/* Deliberately unnumbered. The design direction reserves 01/02/03
                    markers for the case lifecycle, which is genuinely ordered; these
                    four conditions all hold at once when a shot is set up, so numbering
                    them would imply a sequence that does not exist. */}
                <img className="plate__figure" src={plate.src} alt="" />
                <h3 className="plate__heading">{plate.heading}</h3>
                <p className="plate__because">{plate.because}</p>
              </li>
            ))}
          </ul>
          <p className="plate-set__note">
            These plates are illustrations. They are not photographed, uploaded or kept
            with any scan.
          </p>
        </>
      )}
    </section>
  );
}
