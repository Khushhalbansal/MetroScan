# Previous Work — Literature & Landscape Review

**Subject:** automated compliance checking of pre‑packaged commodities against the
**Legal Metrology (Packaged Commodities) Rules, 2011** from product photographs / label
images / e‑commerce listings — i.e. the problem MetroScan solves.

**Reviewed:** 2026‑08‑31.
**Method:** keyword sweeps of Google/Bing web search, GitHub REST search API, IEEE Xplore,
SpringerLink, ScienceDirect, arXiv, ResearchGate, Semantic Scholar, IJRASET/IJAIA and
allied journals, plus SIH problem‑statement catalogues. The problem does not appear under
the name "MetroScan" anywhere; searches were run on the problem statement, the rule set,
the sponsoring ministry, and every adjacent technical sub‑problem (label OCR, key‑information
extraction, nutrition‑panel parsing, font/character‑height measurement, curved‑label
dewarping, e‑commerce listing audit, MRP/dual‑MRP detection).

---

## 0. The problem statement itself

| Cycle | ID | Title | Sponsor | Notes |
|---|---|---|---|---|
| SIH 2025 | **SIH25057** | *Automated Compliance Checker for Legal Metrology Declarations on E‑Commerce Platforms* | MoCA, F&PD | e‑commerce‑listing focus: crawl listings, OCR listing images + text, validate against LM norms, regulator dashboard. |
| SIH 2026 | **SIH26034** | *Software System to check compliance of Packaged Commodities under Legal Metrology (Packaged Commodities) Rules, 2011 by scanning products, images and labels* | MoCA, F&PD | physical‑pack focus: scan a real package/label, extract declarations, judge, produce a citable report. |

MetroScan is squarely a **SIH26034** solution (officer photographs a physical pack; Rule 8
character‑height measurement is central) with the SIH25057 e‑commerce profile as a planned
extension.

**Headline finding:** there is **no peer‑reviewed paper and no mature open‑source project**
that solves this exact problem. What exists is (a) a large cohort of 2025–2026 hackathon
repositories at prototype maturity, almost all built the same way (cloud VLM extraction +
a thin rule engine), and (b) an adjacent academic literature on food/nutrition‑label OCR,
document key‑information extraction, and document dewarping that solves *pieces* of the
pipeline but never the legal‑judgement layer, the Rule 8 physical measurement, or the
"refuse rather than guess" evidentiary discipline.

Sources for this section:
[PIB — DoCA SIH 2025](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2178592) ·
[SIH 2026 problem‑statement catalogue (mirror)](https://github.com/NoBugNinja/Smart-India-Hackathon-SIH-2026-Problem-Statements) ·
[SIH 2026 master catalogue PDF](https://www.blinknbuild.in/Assets/SIH_2026_All_226_Problem_Statements_Master_Catalogue.pdf)

---

## 1. Academic / research literature (2022 onward)

No result directly targets Legal‑Metrology compliance. The closest bodies of work are
grouped below. For each: what it does, method, data, results, limitations, and how it
relates to MetroScan.

### 1.1 Product‑ / food‑label information extraction

| # | Work (venue, year) | Task | Method | Data | Reported result | Key limitations | Relation to MetroScan |
|---|---|---|---|---|---|---|---|
| A1 | **Seitaj & Elangovan, "Information Extraction from Product Labels: A Machine Vision Approach"** — *IJAIA* 15(2), Mar 2024 ([PDF](https://aircconline.com/ijaia/V15N2/15224ijaia04.pdf), [abstract](https://aircconline.com/abstract/ijaia/v15n2/15224ijaia04.html)) | Extract text from grocery labels; expose "directions / ingredients" for visually‑impaired users | CRNN (CNN+RNN) trained on encoded labels + Tesseract OCR + NLP post‑processing; Open Food Facts API for DB population and text‑only prediction | Own label set (size not disclosed in abstract); Open Food Facts | Qualitative "efficacy of DL+OCR"; no headline F1 in abstract | Extraction only — **no rule/compliance layer**, no measurement, no evidentiary handling, small undisclosed dataset | MetroScan does the same extraction step deterministically, then adds the entire legal‑judgement + Rule 8 + reporting stack this paper stops short of |
| A2 | **Shah, "Delving Deep into NutriScan: Automated Nutrition Table Extraction and Ingredient Recognition"** — *IJRASET*, Nov 2023, DOI 10.22214/ijraset.2023.56852 ([page](https://www.ijraset.com/research-paper/delving-deep-into-nutriscan-automated-nutrition-table-extraction)) | Detect the nutrition panel + parse nutrients + recognise ingredients on packaged food | EfficientDet detector fine‑tuned 25 000 steps for panel/table localisation; PaddleOCR for text; **regex** for sodium/carbs/fat/protein/additives/allergens | Own packaged‑food image set | "Enhanced accuracy" from fine‑tuning; no confusion matrix reported | FSSAI/nutrition scope, not Legal Metrology; regex only, no rules engine; single‑image; no confidence/absence handling | Same detector→OCR→regex spine as MetroScan's pipeline; MetroScan adds typed frozen extractions, a versioned rule engine, and cross‑image merge |
| A3 | **"Nutritional Insight: Using OCR to Decode Food Labels for Better Health"** — IEEE conf., 2024/25 ([IEEE 10923764](https://ieeexplore.ieee.org/document/10923764/)) | Read nutrition facts from packaging *without* a product database (vs barcode lookup apps) | OCR + ML extraction & analysis of the nutrition panel | Not disclosed here | Positioned as an upgrade over barcode‑only apps | Nutrition‑panel scope; consumer‑health framing; no regulatory rule engine, no measurement | Shares the "read the label itself, don't trust a database" stance MetroScan takes; MetroScan applies it to statutory declarations, not nutrients |
| A4 | **"Automating Nutritional Claim Verification: The Role of OCR and Machine Learning in Enhancing Food Label Transparency"** — IEEE conf., 2024 ([IEEE 10823177](https://ieeexplore.ieee.org/document/10823177/)) | Verify nutrition *claims* ("low fat", "sugar free") against label data | EasyOCR (deep OCR) + classification algorithms over ingredient/nutrient text | Food‑label images | Data‑driven claim verification demonstrated | Claims‑only; no LM declarations; no evidentiary/override model | Closest analogue to MetroScan's *semantic* Rule 9 misleading‑claim check (which MetroScan deliberately routes to NEEDS_REVIEW rather than auto‑failing) |
| A5 | **"Implementation of Tesseract OCR and Bounding Box for Text Extraction on Food Nutrition Labels"** — *BITS* journal, 2024 ([page](https://ejurnal.seminar-id.com/index.php/bits/article/view/6107)) | Extract nutrition text with bounding boxes | Tesseract + bounding‑box detection | Nutrition‑label images | Working extraction pipeline | No structure recovery, no rules, small scope | Baseline‑tier extraction; MetroScan's `pipeline/ocr.py` reading‑order + span→block localisation is a generation ahead |
| A6 | **"Evaluating OCR Performance on Food Packaging Labels in South Africa"** — Springer *LNNS*, 2025, DOI 10.1007/978‑3‑032‑11733‑5_8 ([chapter](https://link.springer.com/chapter/10.1007/978-3-032-11733-5_8)) | Benchmark 4 open OCR engines on real food packaging (ingredients + nutrition panels) | Tesseract, EasyOCR, PaddleOCR, TrOCR compared on a ground‑truth subset | Real‑world food‑packaging photos | Tesseract lowest CER (0.912) / highest BLEU (0.245) on their subset; EasyOCR best accuracy/multilingual trade‑off | Extraction accuracy only; no downstream task; numbers are poor in absolute terms (glossy/curved packs are hard) | Empirical justification for MetroScan's choice to *harden around* OCR error (confidence floors, `can_assert_absence`) rather than trust raw text |
| A7 | **"A Robust Framework for Coffee Bean Package Label Recognition: Integrating Image Enhancement with Vision–Language OCR Models"** — PMC, 2025 ([PMC12568198](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12568198/)) | Read cluttered decorative package labels | Image‑enhancement front‑end + VLM‑based OCR | Coffee‑package images | Enhancement materially lifts VLM‑OCR on low‑contrast/decorative labels | Single product category; VLM dependency; no compliance layer | Supports MetroScan's `pipeline/preprocess.py` emphasis; MetroScan avoids the VLM dependency |
| A8 | **"HalalBench: A Multilingual OCR Benchmark for Food Packaging Ingredient Extraction"** — arXiv 2604.22754, 2026 (arXiv id surfaced twice; PDF not parsed) | Multilingual OCR benchmark for packaging ingredient lists | Benchmark suite across engines/languages | Multilingual packaging images | Benchmark (numbers not extracted) | Ingredient‑list scope; benchmark, not a method | Signals the multilingual gap MetroScan has today (PP‑OCRv4 English; Devanagari in the design system but not yet in OCR) |
| A9 | **"NutrifyAI: An AI‑Powered System for Real‑Time Food Detection…"** — arXiv 2408.10532, 2024 | Real‑time food/ingredient recognition & nutrition estimation | YOLO‑family detection + API nutrition lookup | Food images | Real‑time demo system | Plate/food recognition, not packaged‑label declarations | Tangential; confirms the detection‑then‑lookup pattern MetroScan explicitly rejects for legal fields |
| A10 | **"The Role of AI and OCR‑Based Label Verification Systems…"** — *IJFMR* 7(2), 2025, paper 41577 ([PDF](https://www.ijfmr.com/papers/2025/2/41577.pdf)) | Survey/positioning of AI + OCR label‑verification systems for packaged‑goods compliance | Review of image‑processing, character recognition and rule‑application approaches (PDF stream corrupted; specifics not recoverable) | — | — (review) | Regulatory domain not pinned to Legal Metrology; no method/benchmark of its own | Confirms the topic is being written about at review level in Indian student journals, but not at the depth of an implemented dated‑rule + measurement system |

### 1.2 Document key‑information extraction (KIE) — the generic version of the "read declarations into a schema" step

| # | Work | Method / contribution | Why it matters here | Gap vs the LM problem |
|---|---|---|---|---|
| B1 | **LayoutLM / LayoutLMv3** (Microsoft; SROIE, CORD, FUNSD benchmarks) | Multimodal (text+layout+image) transformer for KIE; ~0.95 F1 on SROIE's 4 fields | The reference approach for "turn a scanned document into fields" | SROIE has 4 fields on flat receipts; packaging is curved, multi‑panel, glossy, bilingual, and the field set + legal semantics are far larger. No absence/uncertainty semantics. |
| B2 | **Donut / OCR‑free document understanding** | Encoder‑decoder image→JSON, no external OCR | Removes OCR‑cascade latency/errors | Free‑form generation can hallucinate a field value — unacceptable when a wrong value is an accusation against a manufacturer |
| B3 | **STNet — "See then Tell: Enhancing Key Information Extraction with Vision Grounding"** — arXiv 2409.19573, Sep 2024 | `<see>` token forces the model to localise the evidence region *before* emitting the answer; SOTA on CORD/SROIE/DocVQA; introduces the **TVG** dataset | Directly addresses hallucination via **extractive grounding** | Research model, table/receipt domain; MetroScan achieves the same guarantee structurally: `raw_text` (evidence, with span→pixel) is separate from `parsed` (fact), and rules may only read `parsed` |
| B4 | **"Deep Learning based Key Information Extraction from Business Documents: Systematic Literature Review"** — arXiv 2408.06345, 2024 | Survey of the whole KIE field | Positions all of the above | Confirms no KIE work targets statutory‑compliance adjudication or physical measurement |
| B5 | **"LLM‑Based Robust Product Classification in Commerce and Compliance"** — arXiv 2408.05874, 2024 | LLMs for HS‑code / customs product classification under noisy inputs | Nearest "commerce + compliance" ML paper | Classification, not label‑declaration verification; no image side |

### 1.3 Curved‑surface / camera‑captured document rectification (needed for cylindrical packs)

| # | Work | Contribution | Relation to MetroScan |
|---|---|---|---|
| C1 | **UVDoc: Neural Grid‑based Document Unwarping** — arXiv 2302.02887 (SIGGRAPH Asia 2023) | Joint geometric + illumination unwarping with a UV grid | The technique a bottle/tube label needs before OCR *and* before any mm‑per‑pixel measurement is valid |
| C2 | **DocTr / Fourier Document Restoration / D2Dewarp / ForCenNet** (2021–2025) | Progressive SOTA on document dewarping & illumination | Same |
| C3 | Classical **cylindrical label unwrap** (RoboRealm "Bottle Unwrap"; SIFT/ORB + cylindrical projection) | Pre‑OCR curve correction on production lines | Baseline for the same need |
| — | **Gap:** none of these are wired to a compliance or measurement task; MetroScan does not yet do curved‑surface unwarping (roadmap item; see `docs/` and the "risks" table in the plan). |

### 1.4 E‑commerce listing / retail understanding (the SIH25057 side)

| # | Work | Contribution | Relation |
|---|---|---|---|
| D1 | **"Optimizing merchant compliance: A system for product‑specific rule extraction using NLP"** — *MethodsX* / ScienceDirect S2215016126002116, 2026 | Continuously scrapes government regulation repositories, cleans, and uses spaCy NLP to surface product‑specific rules to merchants | Nearest thing to an "automated compliance for online sellers" paper; it extracts *rules from regulation text*, the mirror image of MetroScan's hand‑curated dated YAML | No image/label side; no verdicting of an actual product |
| D2 | **"Adapting Vision‑Language Models for E‑commerce Understanding at Scale"** — arXiv 2602.11733, 2026 | Fine‑tuning VLMs for large‑scale e‑commerce attribute understanding | The infra a listing‑crawl compliance checker would sit on | Attribute extraction, not statutory verdicting |
| D3 | **"What Matters for Grocery Product Retrieval with Open‑Source VLMs"** — arXiv 2605.18029, 2026 (4th GroceryVision Challenge) | 190‑model eval; data quality > scale for grocery product recognition | Product identification, useful for a barcode‑less catalogue match | Retrieval, not compliance |
| D4 | **Amazon ML Challenge 2024** ("Smart Vision") — competition, not a paper ([topic](https://github.com/topics/amazon-ml-challenge)) | Extract weight/volume/dimensions entities from ~250k Amazon product images; winning solutions use PaddleOCR+LLM or VLMs (PaliGemma, Phi‑3‑Vision, LLaVA) | Same "entity from product image" sub‑task, at scale | No rules, no units validation against a statute, no measurement, no report |
| D5 | **"Hierarchical Vision–Language‑Aware Product Detection in Dense Retail Shelves … Enhanced YOLOv12 with Hybrid OCR‑LLM Refinement"** — Research Square rs‑9540033, 2025 | Detect + identify products on dense shelves; YOLOv12 + adaptive OCR‑LLM refinement | Shelf‑audit / planogram lineage; the "detector → OCR → LLM refine" stack | Product identification & inventory, not label‑declaration compliance |
| D6 | **"Detection and Recognition of Price Labels Using OCR and YOLO"** — ReadyTensor, 2024 ([pub](https://app.readytensor.ai/publications/detection-and-recognition-of-price-labels-using-ocr-and-yolo-3Pxbc1GwV0ni)); PLOS One 2025 **YOLOv5 food‑packaging defect detection** ([article](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0321971)) | Price‑tag reading on mobile (YOLOv8+PaddleOCR); packaging *defect* QC | Two more slices of the "detect region → OCR" spine, deployed on mobile / on a line | Price tags and physical defects, not statutory declaration completeness |
| D7 | Regulatory/industry literature: [CLASP.ngo India e‑commerce labelling RFP](https://www.clasp.ngo/rfps/india-e-commerce-labelling/), [S.S. Rana — mandatory declarations by e‑commerce](https://ssrana.in/articles/mandatory-declaration-provisions-ecommerce-india/); industry note that faulty labels were the #1 cause of US food recalls in 2024 (≈83% undeclared allergens — [Jidoka](https://www.jidoka-tech.ai/blogs/what-is-label-inspection-guide)) | Establishes the *non‑compliance prevalence* and recall cost that motivate SIH25057/26034 | Problem evidence, not a solution |

### 1.5 Character‑height / font‑size from imagery (Rule 8)

- No academic work measures **printed character height in millimetres from a consumer
  photograph for a legal threshold.** The typographic literature only covers
  point↔mm conversion in a known print pipeline (1 pt ≈ 0.353 mm; cap‑height ≠ nominal
  size and varies by typeface — [Phinney on Fonts](https://www.thomasphinney.com/2011/03/point-size/),
  [font‑size in mm](https://fontaxis.com/font-size-in-mm/)).
- The nearest patents are about **detecting/reading a label on a curved container** on a
  production line ([US 12,493,983](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12493983))
  and **automated detection of missing / obstructed / damaged labels**
  ([US 10,943,205](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10943205)) —
  label *presence/position*, not glyph height against a legal threshold.
- **This is MetroScan's genuinely novel contribution:** recover mm‑per‑pixel from a
  fiducial of known size (ArUco scale card / ID‑1 card / ₹5–₹10 coin), measure the glyph,
  compare to the dated Rule 8 Table I/II value for the PDP area, and **refuse to measure —
  NEEDS_REVIEW, never FAIL — when no fiducial is present.** No prior art, academic or
  open‑source, does this. The only comparable *statement of intent* is the design doc
  **Pramaan** (§2.2 below).

### 1.6 Commercial & government systems (context, not competitors)

| System | What it is | Relation |
|---|---|---|
| **GlobalVision**, **Mindee "Nutrition Facts Label OCR API"**, **Product Label Guru (LaunchRocket)**, **Artwork Flow** | CPG artwork **proofreading** — compare a print‑ready label to an approved spec / Bill of Materials before it goes to press | Pre‑production, brand‑side, needs the reference artwork; opposite end of the lifecycle from enforcement, which has only a photo of a pack in a market |
| **TN‑LMCTS** (Tamil Nadu Legal Metrology Complaint Tracking System) | Citizen mobile/web app to photograph an overcharged product + shop and file a complaint | Human‑in‑the‑loop complaint intake; **no automated extraction or verdicting** |
| "Dual‑MRP detection rate", "MRP compliance score" etc. as retail **KPIs** ([CAG](https://www.cag.org.in/blogs/maximum-retail-price-mrp-and-over-charging), industry pricing guides) | Audit metrics tracked manually / from POS data | MetroScan can *produce* the dual‑MRP signal per scan (`MRP_SINGLE_VALUE` rule) rather than sampling it |

---

## 2. Open‑source projects

### 2.1 The SIH 2025 / 2026 hackathon cohort

GitHub currently hosts **40+ repositories** against SIH25057 / SIH26034, almost all created
in August 2026, almost all 0–3 stars, most at "prototype / README + partial code" maturity.
They are strikingly homogeneous. The representative and/or most‑developed ones:

| Repo | Stack | Extraction | Rule engine | Distinctive | Maturity | vs MetroScan |
|---|---|---|---|---|---|---|
| **Ujjwal212004/CompliAI** (`SIH25057`, 3★) | Streamlit, Python | **Google Gemini 2.5 Flash Vision**, cascading rule‑based → ML → Gemini | "Complete implementation of LM Rules 2011"; real‑time score; CSV/JSON export | ML feedback loop, dataset manager, retraining from user corrections | Working demo | Cloud‑VLM dependency; no offline path; no physical measurement; no evidence/override/audit model; no dated rulesets |
| **jitendrachoudhary1401‑hue/Parakh** (`26034`) | FastAPI + Flutter, JWT+Argon2, 14 routers, SlowAPI | AI + CV + NLP; **AR (ARCore/ARKit)**; barcode verification; regulatory‑DB cross‑reference | Violation flagging | **Blockchain** tamper‑proof evidence; cryptographic evidence; GPS; offline sync queue; 11 mobile screens | Ambitious, breadth‑first | Same auth stack as MetroScan; broader (mobile+AR+chain) but shallower on rule fidelity and the "refuse to guess" discipline; blockchain is arguably over‑engineering |
| **adarsh005599/legal‑metrology‑compliance‑engin** (`PS‑26034`) | Docker/HF Space, PaddleOCR, ReportLab | PaddleOCR pipeline | **Rule 3 & Rule 26 statutory‑exemption pre‑filter**, then 5‑field engine (MRP+dual‑pricing, net qty+SI units, mfg/pack date, mfr address, consumer care) | Explicit **"compliance‑assist screening report, not a statutory notice"** framing citing LM Act §15 | Single‑file‑ish, focused | Philosophically the closest sibling: exemptions‑first, screening‑not‑determination. MetroScan goes further: 20+ rules, dated rulesets, Rule 8 measurement, `raw_text`/`parsed` split, cross‑image merge, real‑photo regression fixtures |
| **chadavinuthna/SIH26034‑Smart‑Legal‑Metrology** | FastAPI + React, Pydantic | **Gemini** vision → `ProductData` Pydantic schema | Deterministic engine **LM‑001…LM‑009** → PASS/FAIL/REVIEW/NA | Stated principle: *"AI extracts and interprets; deterministic rules make compliance decisions; the AI never directly decides legal status"* | Prototype V1 | Identical design principle and 4‑valued verdict to MetroScan; MetroScan's rule set and hardening are deeper, and it doesn't route legal fields through a cloud model |
| **TushKum/pramaan** | Architecture doc + a "reduced but functional" scanner (Vercel) | Grammar‑constrained decoding; extractive grounding "so no field can be hallucinated" | Versioned rules **with validity intervals**, evaluated against the pack's governing date; **four‑valued** verdict (`compliant/non_compliant/indeterminate/not_applicable`) | Names all four hard capabilities explicitly: **X‑1 physical font measurement via AR/fiducial with propagated uncertainty + guard band**, X‑2 curved‑surface unwarping, X‑3 grammar‑constrained structuring, X‑4 e‑commerce extension | **Design document**, not an implementation | The one project that independently arrived at MetroScan's full thesis (dated rules, 4‑valued verdict, fiducial mm measurement with uncertainty, "a declaration we couldn't read is never a declaration the packer omitted"). MetroScan is the *implemented, tested* version of this vision |
| **adityashirsatrao007/metroscan‑legal‑metrology** | Python, Tesseract / Qwen2‑VL, HF Qwen2‑1.5B‑Instruct | OCR → LLM returns structured JSON → context‑aware regex (MRP must sit next to "MRP"; reject kcal) | **Not built** ("specified in §9, left to finish") | Same *name*; offline‑capable via Tesseract if HF models pre‑downloaded | Extraction half only | Coincidental name clash; extraction‑only, rule engine unimplemented. MetroScan is a complete, tested system |
| **VarnitAgustya27/LEGAL_LENS** (`SIH 2026`) | Next.js + FastAPI + PostgreSQL | AI pipeline with per‑field confidence | Violation flagging; uncertain → `REQUIRES MANUAL VERIFICATION` | "Enforcement‑assistance system, not an autonomous legal decision‑maker" | Prototype | Same disclaimer posture; less depth on rules/measurement/audit |
| **Shards‑Of‑Sapphire/UMVP**, **compliance‑seva** (DevAbhay07), **harshithps35/…LMPC‑Enforcement‑Platform**, **RiteshTalwekar7/MetaCheck**, **abdullaansari‑dotcom/PackCheck** | React/TS or Next.js portals; some with camera capture + dashboards | Varies; several are UI‑first with a stub or cloud OCR | Thin or planned | Workflow/portal framing (LMO scheduling, QR certificates, records management) | Prototype / scaffolding | Portal & UX plays; the extraction/judgement core is not the focus. MetroScan is engine‑first |
| **Long tail** (≈30 more: `urzidan/…`, `sushanth‑10/…`, `laksh2005/automated‑compliance‑checker`, `Giriprasath0307/…`, `ragulmoorthy227‑bot/…`, `vaidehibhojane/…`, `vidhya81206‑lgtm/packCheck‑SIH`, `Nandakishor09/SIH_2026`, `atharvachourasia9373/…`, `Fiza‑syed2007/LM‑Inspect‑AI`, `dhruvramola2417/SIH26034`, `Abhinav5656U/CompliScan`, `arpitpurty106/…`, `tani2112/MetrologyLens`, `brindhaa657/…`, `Kunal‑Ch21/devdrishti‑compliance‑scanner`, `mahivermaix‑web/…`, `madhurgarg5366/BharatVision`, `Varshita‑Reddy/…`, `sahilkumardhiwar96/…`, `prasannavinchurkar‑ui/…`, `Shouryagupta‑10/…`, `yaswanthsetty/legal‑metrology‑ocr‑pipeline`, `Upparivamshidharsagar/PROJECT‑SIH26034`, …) | Mostly Python or JS/TS; frequently Gemini/Claude Vision + regex/rules; some just READMEs | cloud VLM or PaddleOCR/Tesseract | mostly stub / "LM‑001..00N" sketch | occasional dashboard, web crawler, or barcode idea | README → early prototype | Same architecture family; none show evidence of (a) mm measurement with fiducials, (b) dated rulesets judged by scan date, (c) OCR‑failure‑≠‑violation guards with tests, (d) byte‑identical POST/GET rebuild from stored rows, (e) a real‑photo regression suite |

### 2.2 Adjacent open‑source

| Repo | What | Relation |
|---|---|---|
| **Arun‑Sanjay/AI‑Powered‑FSSAI‑Compliance‑Checker** (RVCE, 2025‑26) | **Claude Vision** single‑shot label extraction → 5‑module engine (additives vs 75‑entry permitted DB, 90+ allergen keywords, nutrition‑claim thresholds, 14‑digit FSSAI licence check, mandatory‑field check) → weighted 0–100 risk score + A–F grade; has a CI test badge | Sibling *problem* (FSSAI food safety, not Legal Metrology) with a near‑identical *architecture* to MetroScan minus the measurement layer and the dated‑ruleset / evidence‑separation rigour. Useful comparison for the rule‑engine + weighted‑score pattern |
| **Manika2219/Smart‑Vision‑Technology** | Custom CNN brand classifier + OCR for MRP/mfg/expiry (Amazon‑style) | Brand ID + entity OCR; no compliance |
| **KhadgaA/Amazon‑ML‑Challenge**, **Spartan‑71/Amazon‑ML‑Challenge‑2024** | Winning / strong solutions for entity extraction (weight, volume, dimensions) from product images at scale | The extraction sub‑task done at 250k‑image scale; no units‑vs‑statute validation, no report |

---

## 3. Synthesis — what has been done vs. what MetroScan adds

### 3.1 What the field has collectively solved

- **Label OCR** on packaged goods with open engines (Tesseract/EasyOCR/PaddleOCR/TrOCR) and, increasingly, cloud VLMs — with the well‑documented caveat that accuracy on glossy/curved/low‑contrast retail packs is mediocre (A6).
- **Extracting fields** (MRP, net quantity, dates, manufacturer, nutrition values) via regex/NLP over OCR text or via VLM‑to‑JSON (A1, A2, D4, most hackathon repos).
- **KIE with layout models** and the hallucination fix of **vision‑grounded / extractive** decoding (B1–B3).
- **Document dewarping** as a mature standalone capability (C1–C3).
- The **architectural consensus**, arrived at independently by several 2026 hackathon teams and the Pramaan design doc: *AI extracts, a deterministic rule engine decides, verdicts are ≥3‑valued, and the tool assists an officer rather than issuing a determination.*

### 3.2 What no prior work does — and MetroScan does

1. **Rule 8 as a real physical measurement.** mm‑per‑pixel from a known‑size fiducial;
   glyph height vs. the **dated** Table I/II value for the computed PDP area; and a hard
   refusal (`NOT_MEASURABLE` → NEEDS_REVIEW, never FAIL) when no fiducial is in frame.
   Only Pramaan (X‑1) even proposes this, and it is unimplemented.
2. **Evidence/fact separation enforced structurally.** `raw_text` (with span→block→pixel
   provenance) is evidence; `parsed` is a frozen typed dataclass; **rules may only read
   `parsed`** (guarded by `tests/test_rule_contract.py`; `rules/engine.py` imports no
   `re`). STNet (B3) targets the same goal with a research model; every VLM‑to‑JSON
   hackathon entry is exposed to exactly the hallucinated‑field risk this removes.
3. **"OCR failure ≠ violation."** `ScanContext.can_assert_absence` — a scan that read
   almost nothing may not assert a declaration is missing; a lens‑cap photo is not a pack
   with fifteen violations. No other project has an explicit guard, and none test it.
4. **Dated, versioned rulesets judged by `scan_date`.** A 2019 pack is not judged against
   the 2022 Unit Sale Price rule; a reopened scan is re‑run under its original version.
   Only Pramaan states this ("validity intervals"); MetroScan implements and migrates it.
5. **Byte‑identical POST vs. GET.** The API response is rebuilt from stored rows, and
   tests assert equality — findings can never drift from what was filed.
6. **Cross‑image evidence reconciliation.** A declaration clearly visible in *any*
   submitted photo is judged on that photo, resolved by confidence, not first‑match —
   without ever fabricating a PASS (dedicated tests).
7. **Override without erasure + append‑only audit.** `status` + `original_status` both
   returned; every mutation logged with before/after; findings never outlive their
   evidence (any image edit re‑runs the whole pipeline).
8. **A report that is the same instrument on screen and on paper** — the Rule 8 finding
   rendered as a graduated millimetre rule with a brass limit line, mirrored by
   `reports/measure.py`; DejaVu vendored for the `₹` glyph; template written in the CSS
   subset both PDF engines render.
9. **A real‑photo regression suite.** Officer‑supplied photographs of real packs
   (`tests/golden/…`) are permanent fixtures asserting the finding *statuses* an officer
   should see, with an explicit allow‑list of legitimate FAILs and nothing else permitted
   to fail. No competitor repo shows a comparable test corpus.
10. **Fully offline extraction** (RapidOCR / PP‑OCRv4 via onnxruntime). The rest of the
    cohort depends on Gemini/Claude for the legally‑consequential step.

### 3.3 Where MetroScan is currently *behind* some prior work

| Gap | Who has it | MetroScan status |
|---|---|---|
| **E‑commerce listing crawler** + listing‑profile rules (SIH25057 core: Rule 6(10)) | CompliAI, several SIH25057 repos; D1 for rule‑text scraping | Planned (Phase 7); rule profile stubbed, no crawler |
| **Curved‑surface / cylindrical label dewarping** | C1–C3 literature; Pramaan X‑2 (design) | Not implemented (roadmap risk item) |
| **Multilingual OCR** (Hindi + regional) | EasyOCR‑based repos; A6 notes EasyOCR's multilingual edge; A8 benchmark | English PP‑OCRv4 only; Devanagari is in the design system, not the OCR |
| **Barcode / GS1 / brand‑DB cross‑check** | Parakh, Manika2219, Amazon‑ML solutions | Not implemented (deliberately DB‑independent, but a barcode sanity check is compatible) |
| **Native mobile / AR field app** | Parakh (Flutter+AR), compliance‑seva, LEGAL_LENS | Web + camera capture only; Android app is a plan Phase 5 |
| **VLM fallback for very hard reads** | Most of the cohort | Deliberately omitted; an `Extractor` interface for an optional on‑prem VLM is a design hook, not built |
| **Uncertainty propagation with a guard band on the mm measurement** | Pramaan X‑1 (design) | MetroScan measures and compares; formal error propagation + guard band is a strengthening opportunity |
| **Scale at 250k+ images** | Amazon ML Challenge solutions | MetroScan is officer‑workflow scale, not catalogue scale |

---

## 4. Feature comparison matrix

Legend: ✅ implemented & tested · 🟡 partial / design‑only · ❌ absent · — n/a

| Capability | **MetroScan** | CompliAI | Parakh | LM‑Compliance‑Assist (adarsh) | chadavinuthna 26034 | Pramaan (design) | FSSAI Checker (Arun) | Academic best‑case |
|---|---|---|---|---|---|---|---|---|
| Offline extraction (no cloud LLM for legal fields) | ✅ RapidOCR/PP‑OCRv4 | ❌ Gemini | 🟡 AI+CV | ✅ PaddleOCR | ❌ Gemini | 🟡 (grammar‑constrained local) | ❌ Claude | 🟡 (A2/A6 use local OCR) |
| Typed frozen extractions; rules read parsed only | ✅ (contract‑tested) | ❌ | ❌ | 🟡 | 🟡 Pydantic | 🟡 (stated) | 🟡 | 🟡 STNet grounding (B3) |
| Rule engine ≥ 16 dated rules w/ citations | ✅ ~20+, YAML, dated | 🟡 "complete" (undated) | 🟡 | 🟡 5 fields | 🟡 LM‑001..009 | 🟡 (versioned, design) | 🟡 5 modules (FSSAI) | ❌ |
| Ruleset chosen by scan date / amendment history | ✅ | ❌ | ❌ | ❌ | ❌ | 🟡 validity intervals (design) | ❌ | ❌ |
| Statutory exemption pre‑filter (Rule 3 / 26) | ✅ | ❌ | 🟡 | ✅ (Rule 3 & 26) | 🟡 | 🟡 | — | ❌ |
| **Rule 8 mm character‑height measurement** | ✅ fiducial → mm, Table I/II | ❌ | 🟡 AR (flagged) | ❌ | ❌ | 🟡 X‑1 (design, w/ uncertainty) | ❌ | ❌ (no prior art) |
| Refuse to measure w/o fiducial → NEEDS_REVIEW | ✅ (API accepts no scale param) | — | 🟡 | — | — | 🟡 (design) | — | — |
| "OCR failure ≠ violation" guard, tested | ✅ `can_assert_absence` | ❌ | ❌ | ❌ | 🟡 REVIEW status | 🟡 `indeterminate` (design) | 🟡 | ❌ |
| ≥3‑valued verdict (PASS/FAIL/REVIEW/NA) | ✅ | 🟡 score | 🟡 | ✅ | ✅ 4‑valued | ✅ 4‑valued | 🟡 grade A–F | — |
| Score never shown without coverage | ✅ | ❌ | ❌ | 🟡 | 🟡 | 🟡 | ❌ | — |
| Cross‑image evidence merge by confidence | ✅ tested | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ | 🟡 (multi‑view not addressed) |
| Officer override w/ original_status kept + audit log | ✅ append‑only | 🟡 feedback loop | ✅ (+blockchain) | ❌ | 🟡 | 🟡 | ❌ | — |
| Findings re‑computed on any image edit | ✅ | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ | — |
| POST/GET byte‑identical (rebuilt from DB) | ✅ tested | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — |
| Citable PDF report, same "Measure" instrument as UI | ✅ (2 PDF engines, ₹ font vendored) | 🟡 CSV/JSON | ✅ PDF | ✅ ReportLab PDF | ✅ printable | 🟡 | 🟡 | — |
| Real‑photo regression fixtures w/ expected statuses | ✅ `tests/golden/…` | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 CI tests (unit) | 🟡 (A6 has a GT subset) |
| "Decision support, not determination" disclaimer | ✅ (design + rules) | 🟡 | ✅ | ✅ (cites §15) | ✅ | ✅ | 🟡 | — |
| E‑commerce listing crawl + Rule 6(10) profile | 🟡 planned | ✅ | 🟡 | ❌ | ❌ | 🟡 X‑4 (design) | — | 🟡 D1 (rule‑text only) |
| Curved‑surface dewarping | ❌ roadmap | ❌ | 🟡 AR | ❌ | ❌ | 🟡 X‑2 (design) | ❌ | ✅ C1–C3 (standalone) |
| Multilingual (Hindi/regional) OCR | ❌ (design‑ready) | 🟡 (Gemini) | 🟡 | ❌ | 🟡 (Gemini) | 🟡 | 🟡 (Claude) | 🟡 EasyOCR (A6) |
| Barcode / GS1 / brand‑DB cross‑check | ❌ (by choice) | ❌ | ✅ | ❌ | ❌ | 🟡 | 🟡 (FSSAI DB) | 🟡 D3 retrieval |
| Native mobile / AR field app | 🟡 planned (Phase 5) | ❌ | ✅ Flutter+AR | ❌ | ❌ | 🟡 | ❌ | — |

---

## 5. Bottom line

- **Academic:** the exact problem is unpublished. MetroScan's OCR→extract→rules spine is
  consistent with the food/nutrition‑label literature (A1–A6) and the KIE literature
  (B1–B5); its evidence‑grounding discipline matches the direction of STNet (B3); its
  dewarping gap is covered by mature methods it has not yet adopted (C1–C3). Its Rule 8
  fiducial‑based millimetre measurement, its dated‑ruleset adjudication, and its
  "refuse rather than guess" evidentiary guards **have no academic precedent**.
- **Open source:** a crowded field of 2025–2026 SIH prototypes, overwhelmingly
  *cloud‑VLM → thin rule engine → dashboard*, at README/demo maturity. A handful
  (adarsh's Assist‑Engine, chadavinuthna's 26034, LEGAL_LENS, and especially the
  **Pramaan** design document) independently reach parts of MetroScan's thesis —
  screening‑not‑determination, ≥3‑valued verdicts, deterministic rules over AI extraction,
  fiducial measurement with uncertainty. **None of them combine an implemented, tested
  version of all of it**, and none carry the offline‑OCR, dated‑ruleset, cross‑image‑merge,
  byte‑identical‑persistence, and real‑photo‑regression properties together.
- **Where to iterate next (highest leverage, from the gaps above):** e‑commerce listing
  ingestion + Rule 6(10) profile; curved‑label dewarping (adopt UVDoc/DocTr) so
  mm‑per‑pixel is valid across the panel; Hindi/regional OCR; formal uncertainty
  propagation + guard band on the Rule 8 comparison; an optional on‑prem VLM behind the
  existing `Extractor` interface for salvage reads (kept out of the legal decision path).

---

## Appendix — full source list

**Problem statement / policy**
- https://www.pib.gov.in/PressReleasePage.aspx?PRID=2178592 — DoCA invites SIH 2025 solutions
- https://github.com/NoBugNinja/Smart-India-Hackathon-SIH-2026-Problem-Statements — SIH 2026 PS catalogue (SIH26034)
- https://www.blinknbuild.in/Assets/SIH_2026_All_226_Problem_Statements_Master_Catalogue.pdf
- https://www.clasp.ngo/rfps/india-e-commerce-labelling/ — India e‑commerce labelling RFP
- https://ssrana.in/articles/mandatory-declaration-provisions-ecommerce-india/ — e‑commerce mandatory declarations
- https://www.cag.org.in/blogs/maximum-retail-price-mrp-and-over-charging — MRP / overcharging
- https://megweights.gov.in/acts/Legal-Metrology-Packaged-Commodities-Rules-2011.pdf — the Rules (primary)

**Academic — label / nutrition OCR & extraction**
- https://aircconline.com/ijaia/V15N2/15224ijaia04.pdf — Seitaj & Elangovan, IJAIA 15(2), 2024 (product labels)
- https://aircconline.com/abstract/ijaia/v15n2/15224ijaia04.html — abstract
- https://www.ijraset.com/research-paper/delving-deep-into-nutriscan-automated-nutrition-table-extraction — Shah, NutriScan, IJRASET 2023
- https://ieeexplore.ieee.org/document/10923764/ — Nutritional Insight (IEEE)
- https://ieeexplore.ieee.org/document/10823177/ — Automating Nutritional Claim Verification (IEEE)
- https://ieeexplore.ieee.org/document/10940148/ — NutriScan mobile app (IEEE, 2025)
- https://ejurnal.seminar-id.com/index.php/bits/article/view/6107 — Tesseract + bounding box on nutrition labels (BITS)
- https://link.springer.com/chapter/10.1007/978-3-032-11733-5_8 — OCR engine benchmark on SA food packaging (Springer LNNS, 2025)
- https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12568198/ — Coffee bean package label recognition w/ VLM‑OCR (2025)
- https://arxiv.org/pdf/2408.10532 — NutrifyAI (arXiv, 2024)
- https://www.researchgate.net/publication/387921937 — Automating Nutritional Claim Verification (RG mirror)
- https://arxiv.org/pdf/2604.22754 — HalalBench multilingual food‑packaging OCR benchmark (arXiv, 2026)
- https://www.ijfmr.com/papers/2025/2/41577.pdf — "The Role of AI and OCR‑Based Label Verification Systems…" (IJFMR 7(2), 2025)

**Academic — key information extraction / document AI**
- https://arxiv.org/abs/2409.19573 — STNet, "See then Tell" (vision grounding for KIE), 2024
- https://arxiv.org/pdf/2408.06345 — Systematic review of DL‑based KIE from business documents, 2024
- https://arxiv.org/pdf/2103.10213 — ICDAR2019 SROIE competition (dataset reference)
- https://arxiv.org/abs/2408.05874 — LLM‑based product classification for commerce & compliance, 2024

**Academic — document dewarping (curved packs)**
- https://arxiv.org/pdf/2302.02887 — UVDoc: neural grid‑based document unwarping (SIGGRAPH Asia 2023)
- https://arxiv.org/html/2501.03145v3 — Hybrid DL + cubic‑polynomial geometry restoration (2025)
- https://arxiv.org/pdf/2203.09910 — Fourier Document Restoration
- https://arxiv.org/pdf/2507.08492 — D2Dewarp (2025)
- https://www.roborealm.com/help/Bottle_Unwrap.php — classical cylindrical unwrap

**Academic / competition — e‑commerce & retail**
- https://www.sciencedirect.com/science/article/pii/S2215016126002116 — Merchant compliance via NLP rule extraction (MethodsX, 2026)
- https://arxiv.org/pdf/2602.11733 — Adapting VLMs for e‑commerce understanding at scale (2026)
- https://arxiv.org/html/2605.18029 — Grocery product retrieval with open‑source VLMs (2026)
- https://www.researchsquare.com/article/rs-9540033/v1 — Dense retail‑shelf product detection, YOLOv12 + OCR‑LLM refine (2025)
- https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0321971 — YOLOv5 food‑packaging defect detection (PLOS One, 2025)
- https://app.readytensor.ai/publications/detection-and-recognition-of-price-labels-using-ocr-and-yolo-3Pxbc1GwV0ni — price‑label detection (YOLOv8+PaddleOCR)
- https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10943205 — US patent: automated detection of missing/obstructed/damaged labels
- https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12493983 — US patent: label detection on curved containers
- https://github.com/topics/amazon-ml-challenge — Amazon ML Challenge 2024 (entity extraction from product images)
- https://github.com/KhadgaA/Amazon-ML-Challenge — winning solution
- https://github.com/Spartan-71/Amazon-ML-Challenge-2024

**Open source — SIH 25057 / 26034 cohort (representative)**
- https://github.com/Ujjwal212004/CompliAI
- https://github.com/jitendrachoudhary1401-hue/Parakh
- https://github.com/adarsh005599/legal-metrology-compliance-engin
- https://github.com/chadavinuthna/SIH26034-Smart-Legal-Metrology
- https://github.com/TushKum/pramaan
- https://github.com/adityashirsatrao007/metroscan-legal-metrology
- https://github.com/VarnitAgustya27/LEGAL_LENS
- https://github.com/Shards-Of-Sapphire/Unified-Metrology-Verification-Platform-UMVP
- https://github.com/DevAbhay07/compliance-seva
- https://github.com/harshithps35/Legal-Metrology-Packaged-Commodities-LMPC-AI-Compliance-Enforcement-Platform
- https://github.com/RiteshTalwekar7/MetaCheck
- https://github.com/abdullaansari-dotcom/PackCheck
- https://github.com/Kunal-Ch21/devdrishti-compliance-scanner
- https://github.com/tani2112/MetrologyLens
- https://github.com/madhurgarg5366-prog/BharatVision
- https://github.com/yaswanthsetty/legal-metrology-ocr-pipeline
- https://github.com/laksh2005/automated-compliance-checker
- https://github.com/vaidehibhojane/Legal-Metrology-Compliance-Checker
- https://github.com/dhruvramola2417/SIH26034
- https://github.com/Fiza-syed2007/LM-Inspect-AI
- (+ ~20 further near‑duplicate repositories under the same two PS IDs)

**Open source — adjacent**
- https://github.com/Arun-Sanjay/AI-Powered-FSSAI-Compliance-Checker — Claude Vision + modular FSSAI rule engine
- https://github.com/Manika2219/Smart-Vision-Technology — CNN brand ID + OCR for MRP/expiry

**Commercial / government context**
- https://www.globalvision.co/blog/how-ai-is-transforming-label-compliance — CPG artwork proofing
- https://www.mindee.com/blog/nutrition-facts-label-ocr-api-streamlining-food-label-compliance-and-data-management
- https://launchrocket.in/product-label-guru/ — Indian marketplace label compliance service
- TN‑LMCTS — Tamil Nadu Legal Metrology Complaint Tracking System (citizen complaint app)
