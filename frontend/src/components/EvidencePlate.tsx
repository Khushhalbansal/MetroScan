/*
  The evidence: the photograph, with a box on every declaration a finding cited.

  Boxes stroke-draw onto the image in sequence when results land — the one orchestrated
  moment in the interface. It is not decoration: the sequence is the order the ledger
  is in, so the eye is walked from the worst finding to the least.

  Images are fetched with the auth header and turned into blob URLs, because evidence
  is behind the same authentication as the finding it supports.
*/

import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { FindingStatus, ScanImage } from "../api/types";
import "./EvidencePlate.css";

export interface Box {
  ruleId: string;
  bbox: [number, number, number, number];
  status: FindingStatus;
  imageId: string;
}

interface Props {
  scanId: string;
  images: ScanImage[];
  boxes: Box[];
  active: string | null;
  onHover: (ruleId: string | null) => void;
  onSelect: (ruleId: string) => void;
}

export function EvidencePlate({ scanId, images, boxes, active, onHover, onSelect }: Props) {
  const [index, setIndex] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const image = images[index];

  useEffect(() => {
    if (!image) return;
    let url: string | null = null;
    let live = true;
    setFailed(false);
    setSrc(null);
    api
      .authedBlob(api.imageUrl(scanId, image.image_id))
      .then((blob) => {
        if (!live) {
          URL.revokeObjectURL(blob);
          return;
        }
        url = blob;
        setSrc(blob);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [scanId, image]);

  if (!image) {
    return <p className="plate__none">No photograph was stored with this scan.</p>;
  }

  const shown = boxes.filter((b) => b.imageId === image.image_id);

  return (
    <figure className="plate">
      <div className="plate__frame">
        {failed ? (
          <p className="plate__none">
            The evidence image could not be loaded. The finding still stands on the
            record, but it cannot be checked against the photograph here.
          </p>
        ) : (
          src && <img className="plate__image" src={src} alt={`Package, ${image.kind.toLowerCase()}`} />
        )}

        {src && (
          <svg
            className="plate__overlay"
            viewBox={`0 0 ${image.width} ${image.height}`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {shown.map((box, i) => {
              const [x, y, w, h] = box.bbox;
              const perimeter = 2 * (w + h);
              const isActive = active === box.ruleId;
              return (
                <rect
                  key={box.ruleId}
                  x={x}
                  y={y}
                  width={w}
                  height={h}
                  className={`plate__box plate__box--${box.status} ${isActive ? "is-active" : ""}`}
                  style={{
                    strokeDasharray: perimeter,
                    strokeDashoffset: perimeter,
                    animationDelay: `${Math.min(i, 14) * 55}ms`,
                  }}
                  vectorEffect="non-scaling-stroke"
                  onMouseEnter={() => onHover(box.ruleId)}
                  onMouseLeave={() => onHover(null)}
                  onClick={() => onSelect(box.ruleId)}
                />
              );
            })}
          </svg>
        )}
      </div>

      <figcaption className="plate__caption">
        {images.length > 1 && (
          <div className="plate__tabs" role="tablist" aria-label="Photographs">
            {images.map((candidate, i) => (
              <button
                key={candidate.image_id}
                type="button"
                role="tab"
                aria-selected={i === index}
                className={`plate__tab ${i === index ? "is-active" : ""}`}
                onClick={() => setIndex(i)}
              >
                {candidate.kind.toLowerCase()}
              </button>
            ))}
          </div>
        )}
        <p className="plate__meta data">
          {image.width}×{image.height} px · {image.blocks_read} text regions read
        </p>
      </figcaption>
    </figure>
  );
}
