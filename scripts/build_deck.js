/**
 * Builds the pitch deck for the SME Finance Copilot.
 *
 *   node scripts/build_deck.js [outputPath]
 *
 * Every figure is read from docs/evidence/facts.json, which
 * scripts/generate_evidence.py computes from the running system. No euro amount
 * is typed into this file by hand - tests/test_consistency.py fails if one is -
 * so the deck cannot contradict the product or the documentation.
 */

const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const FACTS_FILE = path.join(__dirname, "..", "docs", "evidence", "facts.json");
const MARKET_FILE = path.join(__dirname, "..", "data", "market.json");
const F = JSON.parse(fs.readFileSync(FACTS_FILE, "utf8"));
const MK = JSON.parse(fs.readFileSync(MARKET_FILE, "utf8"));
const H = F.hero;
const L = F.lina;
const A = F.accuracy;
const W_IF = F.whatif_demo;
const OUT = process.argv[2] || "SME-Finance-Copilot-Pitch.pptx";

// ---- formatting: identical conventions to app/facts.py ----------------------
const eur = (n) => (n < 0 ? "-" : "") + "EUR " + Math.round(Math.abs(n)).toLocaleString("en-US");
const pct = (n, d = 1) => (n * 100).toFixed(d) + "%";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const day = (iso) => { const [, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]}`; };
const stress = (key) => A.stress.results.find((r) => r.key === key);

// ---- market figures: read from data/market.json, never typed by hand ---------
const mk = (key) => {
  const e = MK.measured[key] || MK.derived[key];
  if (!e) throw new Error(`market.json has no figure '${key}'`);
  return e.value;
};
const mkPct = (key) => mk(key) + "%";
const compact = (n) => {
  if (n >= 1e12) return (n / 1e12).toFixed(1).replace(/\.0$/, "") + " trillion";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "m";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "k";
  return String(n);
};
const mkSource = (key) => {
  const e = MK.measured[key] || MK.derived[key];
  return e.source ? MK.sources[e.source].publisher : "derived in data/market.json";
};


// ---- design system: "cream editorial" ------------------------------------------
// Cream ground, near-black ink, one orange accent. Big solid numbers. One motif
// built from the product itself: the payout track, money moving from the
// marketplace to the bank. The footer track is the slide counter: the dot moves
// one stop per slide and reaches the bank on the closing slide.
const CREAM = "F4EFE6", PANEL = "EAE2D3", HAIR = "D6CCBA";
const INK = "141414", GREY = "5F594F", SOFT = "A39C90";
const ORANGE = "FF5A1F", ORANGE_TXT = "C2410C", GREEN = "2F6B3F", RED = "B42318";
const HEAD = "Archivo Black", BODY = "Calibri", MONO = "Courier New";
const ASSETS = path.join(__dirname, "..", "docs", "deck-assets");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Fintechathon International Track - Topic E";
pres.title = "SME Finance Copilot";
const W = 13.333, M = 0.65;
const MAIN_TOTAL = 13;
let mainIdx = 0;

const VERDICT_COLOR = { fixes: GREEN, avoids_negative: GREEN, improves: ORANGE_TXT,
  no_effect: GREY, worsens: RED, breaks: RED };
const VERDICT_LABEL = { fixes: "fixes it", avoids_negative: "stays out of the red",
  improves: "still goes negative", no_effect: "no effect", worsens: "makes it worse",
  breaks: "breaks it" };

// ---- helpers ---------------------------------------------------------------------
function text(s, t, opts) {
  s.addText(t, Object.assign({ isTextBox: true, margin: 0, fontFace: BODY, fontSize: 13, color: INK }, opts));
}

// "Plain words [accent words]" -> runs; bracketed words take the accent colour.
function runs(str, base, accent, extra) {
  return str.split(/(\[[^\]]+\])/).filter(Boolean).map((p) => {
    const hit = p.startsWith("[");
    return { text: hit ? p.slice(1, -1) : p, options: Object.assign({ color: hit ? accent : base }, extra || {}) };
  });
}

function track(s, x1, x2, y, n, cur, dark) {
  const line = dark ? "4A463F" : HAIR;
  s.addShape(pres.ShapeType.line, { x: x1, y, w: x2 - x1, h: 0, line: { color: line, width: 1 } });
  for (let i = 0; i < n; i++) {
    const cx = x1 + (x2 - x1) * (i / (n - 1));
    const on = i === cur, d = on ? 0.15 : 0.07;
    s.addShape(pres.ShapeType.ellipse, { x: cx - d / 2, y: y - d / 2, w: d, h: d,
      fill: { color: on ? ORANGE : (i < cur ? (dark ? SOFT : GREY) : (dark ? "4A463F" : HAIR)) }, line: { type: "none" } });
  }
}

function footer(s, dark, appendixLabel) {
  const c = dark ? SOFT : GREY;
  text(s, "SME Finance Copilot", { x: M, y: 7.02, w: 3, h: 0.25, fontSize: 10, color: c });
  if (appendixLabel) {
    text(s, appendixLabel, { x: W - M - 3, y: 7.02, w: 3, h: 0.25, fontSize: 10, color: c, align: "right", bold: true });
    return;
  }
  mainIdx += 1;
  text(s, "MARKETPLACE", { x: 3.55, y: 7.03, w: 1.3, h: 0.22, fontSize: 8, color: c, align: "right", charSpacing: 1 });
  track(s, 5.0, 8.35, 7.14, MAIN_TOTAL, mainIdx - 1, dark);
  text(s, "BANK", { x: 8.5, y: 7.03, w: 0.8, h: 0.22, fontSize: 8, color: c, charSpacing: 1 });
  text(s, `${String(mainIdx).padStart(2, "0")} / ${MAIN_TOTAL}`, { x: W - M - 1.5, y: 7.02, w: 1.5, h: 0.25, fontSize: 10, color: c, align: "right", bold: true });
}

function slide(bg, kicker, title, opts) {
  const o = opts || {};
  const s = pres.addSlide();
  const dark = bg === INK;
  s.background = { color: bg };
  const base = bg === CREAM ? INK : (dark ? CREAM : INK);
  const accent = bg === ORANGE ? CREAM : ORANGE;
  if (kicker) text(s, kicker.toUpperCase(), { x: M, y: 0.45, w: 10, h: 0.25, fontSize: 11, bold: true, color: dark ? SOFT : (bg === ORANGE ? INK : GREY), charSpacing: 2 });
  if (title) s.addText(runs(title.toUpperCase(), base, accent), { x: M, y: 0.74, w: W - 2 * M, h: o.titleH || 0.95, isTextBox: true, margin: 0,
    fontFace: HEAD, fontSize: o.titleSize || 28, valign: "top", lineSpacingMultiple: 0.95 });
  footer(s, dark, o.appendix);
  return s;
}

function panel(s, x, y, w, h, fill) {
  s.addShape(pres.ShapeType.rect, { x, y, w, h, fill: { color: fill || PANEL }, line: { type: "none" } });
}

// Big number. Solid fills only: outlined (hollow) text disappears in PDF export,
// Keynote and Google Slides, so it is not used anywhere in this deck.
function big(s, { x, y, w, value, label, color, size, labelColor, labelSize }) {
  const sz = size || 34;
  s.addText(value, { x, y, w, h: sz / 60, isTextBox: true, margin: 0, fontFace: HEAD, fontSize: sz,
    valign: "bottom", color: color || INK });
  if (label) text(s, label, { x, y: y + sz / 60 + 0.08, w, h: 0.6, fontSize: labelSize || 12, color: labelColor || GREY, lineSpacingMultiple: 1.05, valign: "top" });
}

function num(s, x, y, n) {
  s.addText(String(n).padStart(2, "0"), { x, y, w: 0.65, h: 0.4, isTextBox: true, margin: 0, fontFace: HEAD, fontSize: 18,
    color: ORANGE, valign: "top" });
}

function pill(s, t, x, y, w, fill, color) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h: 0.32, rectRadius: 0.16, fill: { color: fill || ORANGE }, line: { type: "none" } });
  text(s, t, { x, y, w, h: 0.32, align: "center", valign: "middle", fontSize: 10.5, bold: true, color: color || INK, charSpacing: 1 });
}

function lineChart(s, series, opts) {
  s.addChart(pres.ChartType.line, series, Object.assign({
    showTitle: true, titleFontSize: 12, titleColor: GREY, titleFontFace: BODY,
    lineSize: 2.75, lineSmooth: false, lineDataSymbol: "none", showValue: false,
    catAxisLabelColor: GREY, catAxisLabelFontSize: 10, catAxisLineColor: HAIR,
    valAxisLabelColor: GREY, valAxisLabelFontSize: 10, valAxisLabelFormatCode: "#,##0", valAxisLineShow: false,
    valGridLine: { color: HAIR, size: 0.75 }, catGridLine: { style: "none" },
    plotArea: { fill: { color: CREAM } }, chartArea: { fill: { color: CREAM } },
  }, opts));
}

/* 1. Title ---------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Fintechathon 2026  ·  International Track  ·  Topic E", null);
  text(s, "YOUR MONEY IS", { x: M, y: 1.15, w: 8, h: 0.8, fontFace: HEAD, fontSize: 44 });
  s.addText("STUCK", { x: M - 0.05, y: 1.85, w: 9, h: 1.6, isTextBox: true, margin: 0, fontFace: HEAD, fontSize: 120,
    color: INK, valign: "middle" });
  s.addText(runs("IN [TRANSIT]", INK, ORANGE), { x: M, y: 3.35, w: 8, h: 0.8, isTextBox: true, margin: 0, fontFace: HEAD, fontSize: 44 });

  // The motif: earned money travelling from the marketplace to the bank.
  const y = 5.05;
  text(s, "MARKETPLACE", { x: M, y: y - 0.48, w: 2.5, h: 0.25, fontSize: 10.5, bold: true, color: GREY, charSpacing: 1.5 });
  text(s, "BANK", { x: 11.0, y: y - 0.48, w: 1.68, h: 0.25, fontSize: 10.5, bold: true, color: GREY, charSpacing: 1.5, align: "right" });
  s.addShape(pres.ShapeType.line, { x: M, y, w: 12.03, h: 0, line: { color: INK, width: 1.5 } });
  [0.05, 0.2, 0.35, 0.5].forEach((t) => {
    s.addShape(pres.ShapeType.ellipse, { x: M + 12.03 * t - 0.09, y: y - 0.09, w: 0.18, h: 0.18, fill: { color: ORANGE }, line: { type: "none" } });
  });
  s.addShape(pres.ShapeType.ellipse, { x: M + 12.03 - 0.16, y: y - 0.16, w: 0.32, h: 0.32, fill: { color: CREAM }, line: { color: INK, width: 1.5 } });
  text(s, [{ text: eur(H.platform_balance), options: { bold: true, color: ORANGE_TXT } },
    { text: " earned, waiting in the payout queue", options: { color: GREY } }], { x: M, y: y + 0.2, w: 7, h: 0.3, fontSize: 13 });
  text(s, [{ text: eur(H.bank_balance), options: { bold: true } }, { text: " in the bank", options: { color: GREY } }],
    { x: 8.3, y: y + 0.2, w: 4.38, h: 0.3, fontSize: 13, align: "right" });

  text(s, [{ text: "SME Finance Copilot", options: { bold: true } },
    { text: ": an AI finance copilot for small businesses whose money arrives late. It finds the gap, tests the real options, and cannot act without you.", options: { color: GREY } }],
  { x: M, y: 5.85, w: 10.5, h: 0.6, fontSize: 14, lineSpacingMultiple: 1.1 });
  text(s, "Theme: AI as a Financial Participant  ·  All data simulated", { x: M, y: 6.48, w: 8, h: 0.3, fontSize: 11, color: GREY });
  s.addNotes("One line: small online sellers can have money left over every month and still be illiquid, " +
    "because marketplaces hold their money. The agent finds the gap, tests every option by simulation, " +
    "and is architecturally unable to act without human approval. Everything runs on simulated data. " +
    "The dots along the bottom of every slide are the payout queue: they reach the bank on the last slide.");
}

/* 2. The problem ------------------------------------------------------------------- */
{
  const s = slide(CREAM, "The problem", "Money left over every month. About to [miss a payment.]", { titleH: 1.0 });
  text(s, `${H.name}  ·  Berlin  ·  print-on-demand apparel`, { x: M, y: 1.95, w: 6, h: 0.3, fontSize: 12.5, bold: true, color: ORANGE_TXT });
  big(s, { x: M, y: 2.4, w: 3.0, value: eur(H.monthly_revenue), label: "monthly revenue", size: 30 });
  big(s, { x: M + 3.2, y: 2.4, w: 3.0, value: eur(H.monthly_cash_surplus), label: "left over monthly, after all regular payments incl. loan", size: 30 });
  big(s, { x: M, y: 3.95, w: 3.0, value: eur(H.bank_balance), label: "in the bank today", size: 30 });
  big(s, { x: M + 3.2, y: 3.95, w: 3.0, value: eur(H.bill_amount), label: `stock bill due ${day(H.bill_due)}`, size: 30, color: ORANGE });

  panel(s, 7.25, 1.95, 5.43, 3.65, INK);
  text(s, "SHE ISN'T BADLY RUN.", { x: 7.6, y: 2.2, w: 4.8, h: 0.4, fontFace: HEAD, fontSize: 18, color: CREAM });
  text(s, "SHE IS ILLIQUID.", { x: 7.6, y: 2.58, w: 4.8, h: 0.4, fontFace: HEAD, fontSize: 18, color: ORANGE });
  text(s, [
    { text: `${eur(H.platform_balance)} of her own money is already earned, waiting in the marketplace payout queue.`, options: { bullet: { indent: 14 }, breakLine: true } },
    { text: `Payouts run every ${H.payout_cadence_days} days, after a ${H.payout_hold_days}-day hold.`, options: { bullet: { indent: 14 }, breakLine: true } },
    { text: `That's ${H.trapped_days} days of sales she can't touch.`, options: { bullet: { indent: 14 } } },
  ], { x: 7.6, y: 3.2, w: 4.8, h: 2.2, fontSize: 14, color: CREAM, paraSpaceAfter: 8, lineSpacingMultiple: 1.1, valign: "top" });

  text(s, "Her bank app shows a balance and her accountant sees a year of profit. " +
    `Neither tells her she goes negative on ${day(H.first_negative_date)}.`,
  { x: M, y: 5.95, w: W - 2 * M, h: 0.6, fontSize: 15, italic: true, color: GREY });
  s.addNotes("'Left over after all regular payments' is deliberate wording: it includes her loan " +
    "repayment, which is a cash outflow but not an accounting expense, so it is not called profit.");
}

/* 3. Why SMEs ------------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Focus", "Why small businesses, and why [online sellers] first");
  [["eu_sme_share_of_enterprises", "of EU enterprises are SMEs"],
    ["eu_micro_share_of_smes", "of those are micro-businesses"],
    ["eu_sme_employment_share", "of EU employment"],
    ["eu_sme_value_added_share", "of EU value added"]].forEach(([k, l], i) => {
    big(s, { x: M + i * 3.05, y: 2.0, w: 2.9, value: mkPct(k), label: l, size: 34 });
  });
  const rows = [
    ["The gap is advice, not just credit",
      "A company with a CFO knows the squeeze is coming. A micro-business finds out when a payment bounces. That asymmetry is what an AI participant can close."],
    ["Online sellers feel it most",
      "Every marketplace holds funds by design, so the squeeze returns at every stock purchase. And the data is transaction-shaped, so honest modelling is possible today."],
    ["The engine is not about e-commerce",
      "A payout queue, card settlement and 60-day invoice terms are one mechanic: money earned and not yet received. A clinic waiting on insurers runs through the same model."],
  ];
  rows.forEach(([t, d], i) => {
    const y = 3.5 + i * 1.07;
    s.addShape(pres.ShapeType.line, { x: M, y: y - 0.12, w: W - 2 * M, h: 0, line: { color: HAIR, width: 0.75 } });
    num(s, M, y, i + 1);
    text(s, t, { x: M + 0.8, y: y + 0.02, w: 4.5, h: 0.8, fontFace: HEAD, fontSize: 14, valign: "top" });
    text(s, d, { x: 6.1, y: y + 0.02, w: 6.58, h: 0.95, fontSize: 13, color: GREY, lineSpacingMultiple: 1.05, valign: "top" });
  });
  text(s, `Source: ${mkSource("eu_smes")}, ${MK.sources[MK.measured.eu_smes.source].name}.`,
    { x: M, y: 6.68, w: W - 2 * M, h: 0.25, fontSize: 10, color: GREY });
  s.addNotes("Answer to 'why SMEs': the credit gap is well known, the advice gap is not, and the advice gap is the one " +
    "an AI can close at near-zero marginal cost. Online sellers are a wedge, not the market.");
}

/* 4. Market ------------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Market", "A narrow wedge into a [very large gap]");
  const cols = [
    ["Start here", mkPct("eu_small_enterprises_selling_online_pct"), "Marketplace sellers",
      "of small EU firms (10-49 staff) already sell online. Eurostat does not measure firms under 10, so we do not invent a count for our starting segment."],
    ["Same engine", compact(mk("adjacent_smes")), "Paid on a delay",
      "EU micro-enterprises. Card settlement, invoice terms and platform payouts are the same mechanic: a data-source problem, not a new forecaster."],
    ["Same problem, bigger", `USD ${compact(mk("msme_finance_gap_usd"))}`, "Unmet MSME finance",
      "across 119 emerging and developing economies, where micro-businesses are most of the employment and the least served."],
  ];
  cols.forEach(([k, v, h, d], i) => {
    const x = M + i * 4.08;
    text(s, k.toUpperCase(), { x, y: 1.9, w: 3.8, h: 0.25, fontSize: 10.5, bold: true, color: ORANGE_TXT, charSpacing: 1.5 });
    big(s, { x, y: 2.2, w: 3.8, value: v, size: i === 2 ? 30 : 38, color: i === 0 ? ORANGE : INK });
    text(s, h, { x, y: 2.95, w: 3.8, h: 0.35, fontFace: HEAD, fontSize: 14 });
    text(s, d, { x, y: 3.32, w: 3.75, h: 1.1, fontSize: 12, color: GREY, lineSpacingMultiple: 1.05, valign: "top" });
  });

  panel(s, M, 4.65, 6.0, 1.75);
  text(s, "HOW IT MAKES MONEY", { x: M + 0.3, y: 4.82, w: 5.4, h: 0.25, fontSize: 10.5, bold: true, color: GREY, charSpacing: 1.5 });
  text(s, [
    { text: "The distributor pays, not the lender. ", options: { bold: true } },
    { text: `A bank, marketplace or accounting platform offers it to its businesses at EUR ${mk("price_per_seller_month_eur")} per business per month. ` +
      `One deployment with ${compact(mk("deployment_active_sellers"))} active sellers is EUR ${compact(mk("deployment_annual_revenue_eur"))} a year. Both inputs are assumptions, labelled as such in data/market.json.` },
  ], { x: M + 0.3, y: 5.12, w: 5.45, h: 1.2, fontSize: 12, lineSpacingMultiple: 1.05, valign: "top" });

  panel(s, 6.95, 4.65, 5.73, 1.75, INK);
  text(s, "WHAT WE REFUSE TO CHARGE FOR", { x: 7.25, y: 4.82, w: 5.2, h: 0.25, fontSize: 10.5, bold: true, color: ORANGE, charSpacing: 1.5 });
  text(s, "No referral fee from lenders. The moment placement can be bought, the ranking is for sale. It is also the only way a tool can honestly say: don't borrow, ask for an early payout instead.",
    { x: 7.25, y: 5.12, w: 5.15, h: 1.2, fontSize: 12, color: CREAM, lineSpacingMultiple: 1.05, valign: "top" });

  text(s, `Sources: ${MK.sources.ec_sme_report_2025_2026.publisher}, ${MK.sources.eurostat_ecommerce_2023.publisher}, ${MK.sources.worldbank_sme_finance.publisher}. Every figure, measured or assumed, is listed with its method in data/market.json.`,
    { x: M, y: 6.6, w: W - 2 * M, h: 0.3, fontSize: 10, color: GREY });
  s.addNotes("If asked which numbers are real: the enterprise counts, the online-selling rate and the financing gap are published by " +
    "the European Commission, Eurostat and the World Bank. We deliberately do not estimate how many micro-businesses sell online, " +
    "because Eurostat does not survey firms under ten people. The price and the deployment size are assumptions. " +
    "If asked 'what if the deploying bank is itself a lender?': its own products go through the same eligibility check and the same " +
    "simulation as every other product, are labelled as the host's own, and the ranking is by simulated cost, not by who deployed us.");
}

/* 5. Two ledgers (full orange: the core idea) --------------------------------------------- */
{
  const s = slide(ORANGE, "Core mechanic", "The insight other tools [model away]");
  text(s, "Consumer finance tools model one account. These businesses have two, and the crisis happens in the gap between them.",
    { x: M, y: 1.75, w: 11.5, h: 0.5, fontSize: 15, color: INK });
  const card2 = (x, title, formula, body) => {
    panel(s, x, 2.5, 5.1, 2.55, CREAM);
    text(s, title.toUpperCase(), { x: x + 0.35, y: 2.75, w: 4.4, h: 0.4, fontFace: HEAD, fontSize: 18 });
    text(s, formula, { x: x + 0.35, y: 3.25, w: 4.5, h: 0.3, fontFace: MONO, fontSize: 12, color: ORANGE_TXT, bold: true });
    text(s, body, { x: x + 0.35, y: 3.7, w: 4.4, h: 1.2, fontSize: 13, color: GREY, lineSpacingMultiple: 1.05, valign: "top" });
  };
  card2(M, "Platform balance", "sales - fees - refunds - payouts",
    "Money she has earned but can't spend. Released on the payout schedule, after the hold, minus a rolling reserve.");
  card2(7.58, "Bank balance", "opening + payouts - expenses",
    "The only money that can pay a supplier. This is what the forecast projects, day by day.");
  s.addShape(pres.ShapeType.rightArrow, { x: 5.95, y: 3.45, w: 1.4, h: 0.55, fill: { color: INK }, line: { type: "none" } });
  text(s, `every ${H.payout_cadence_days} days, after a ${H.payout_hold_days}-day hold`, { x: 5.8, y: 4.08, w: 1.7, h: 0.6, align: "center", fontSize: 11, bold: true, color: INK });
  text(s, [
    { text: "So the copilot can say: " },
    { text: `"you're short because ${H.trapped_days} days of your sales are locked in a queue."`, options: { bold: true } },
    { text: " That's a cause, not just a number." },
  ], { x: M, y: 5.45, w: W - 2 * M, h: 0.8, fontSize: 17, color: INK, lineSpacingMultiple: 1.05 });
}

/* 6. What it does -------------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Capabilities", "What it [does]");
  const items = [
    ["Cash-flow alerts", "Projects the bank balance day by day and names the payment causing the squeeze, how much, for how long, and the time left to arrange it."],
    ["Financing matching", `${F.counts.products} illustrative products, checked criterion by criterion, then simulated with real repayments before any is recommended.`],
    ["Financial analysis", "Contribution margin, break-even, cash left over each month, peer comparison, and money trapped in the payout queue."],
    ["What-if simulator", "Pay a bill later, cut ads, late payouts, take a loan. See the effect before committing. It changes nothing."],
  ];
  items.forEach(([t, d], i) => {
    const y = 1.85 + i * 1.08;
    num(s, M, y, i + 1);
    text(s, t, { x: M + 0.75, y: y + 0.02, w: 4.6, h: 0.35, fontFace: HEAD, fontSize: 15 });
    text(s, d, { x: M + 0.75, y: y + 0.38, w: 4.55, h: 0.68, fontSize: 12, color: GREY, lineSpacingMultiple: 1.0, valign: "top" });
  });
  // Product shot: the running app answering the hero question.
  panel(s, 6.35, 1.8, 6.33, 4.25, INK);
  s.addImage({ path: path.join(ASSETS, "app_alert.png"), x: 6.5, y: 1.95, w: 6.03, h: 3.776 });
  text(s, "The running app, offline mode: the answer to 'Will I run out of cash in the next two months?'", { x: 6.5, y: 5.76, w: 6.03, h: 0.25, fontSize: 10, color: SOFT });
  text(s, [
    { text: "The tools do the arithmetic. The model plans and explains. ", options: { bold: true } },
    { text: "Every figure comes from deterministic code, so the system runs without an API key and judges get the same numbers we do." },
  ], { x: M, y: 6.25, w: W - 2 * M, h: 0.6, fontSize: 13, lineSpacingMultiple: 1.05 });
}

/* 7. What it tells her -------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Demo", "What it actually [tells her]");
  lineChart(s, [{ name: "Projected bank balance", labels: H.balance_series.map((p) => p[0]),
    values: H.balance_series.map((p) => Math.round(p[1])) }],
  { x: M - 0.1, y: 1.8, w: 7.6, h: 3.85, title: "Projected bank balance, next 60 days (EUR)", chartColors: [ORANGE], showLegend: false });

  panel(s, 8.0, 1.85, 4.68, 3.8, INK);
  text(s, "GOES NEGATIVE", { x: 8.35, y: 2.08, w: 4, h: 0.25, fontSize: 11, bold: true, color: SOFT, charSpacing: 1.5 });
  text(s, day(H.first_negative_date).toUpperCase(), { x: 8.35, y: 2.36, w: 4.1, h: 0.6, fontFace: HEAD, fontSize: 30, color: ORANGE });
  [["Lowest point", `${eur(H.trough_balance)} on ${day(H.trough_date)}`],
    ["Needs", eur(H.need_amount)],
    ["For", `${H.need_days} days`],
    ["Time to arrange it", `${H.lead_days} days`]].forEach(([k, v], i) => {
    const fy = 3.15 + i * 0.44;
    text(s, k, { x: 8.35, y: fy, w: 1.9, h: 0.32, fontSize: 13, color: SOFT });
    text(s, v, { x: 10.2, y: fy, w: 2.2, h: 0.32, align: "right", fontSize: 13, bold: true, color: CREAM });
  });
  text(s, `Cause: ${H.bill_counterparty}, ${eur(H.bill_amount)}`, { x: 8.35, y: 5.0, w: 4.1, h: 0.4, fontSize: 12.5, italic: true, color: ORANGE });

  text(s, [
    { text: "A timing problem, not a failing business: ", options: { bold: true } },
    { text: `with no action she recovers to ${eur(H.balance_day_60)} by day 60. Before it mentions borrowing, it offers the free levers first: an early payout, pausing ads, talking to the supplier.` },
  ], { x: M, y: 5.95, w: W - 2 * M, h: 0.75, fontSize: 13.5, lineSpacingMultiple: 1.05 });
  s.addNotes("The early-payout lever names the payout that lands after the squeeze starts, and says plainly that it covers the first dip " +
    "but not the stock bill, because that payout is already counted in the forecast.");
}

/* 8. Lead time vs duration ---------------------------------------------------------------- */
{
  const s = slide(CREAM, "Differentiator", "The distinction a generic assistant [gets wrong]");
  big(s, { x: M, y: 1.75, w: 5.7, value: `${H.need_days} DAYS`, label: "how long the money is needed FOR: drives the cost", size: 46, labelSize: 13 });
  big(s, { x: 6.9, y: 1.75, w: 5.7, value: `${H.lead_days} DAYS`, label: "how long there is to ARRANGE it: drives what is possible", size: 46, color: ORANGE, labelSize: 13 });

  const c = H.cheapest_overall, r = H.recommended, m = H.mca;
  const hdr = ["Product", `Cost for ${H.need_days} days`, "Arranges in", "Tested by simulation"].map((t) =>
    ({ text: t, options: { bold: true, color: CREAM, fontSize: 12, fill: { color: INK } } }));
  const row = (name, cost, speed, note, color, hl) => [
    { text: name, options: { fontSize: 13, bold: hl, fill: { color: hl ? PANEL : CREAM } } },
    { text: eur(cost), options: { fontSize: 13, align: "right", bold: hl, fill: { color: hl ? PANEL : CREAM } } },
    { text: `${speed} day${speed === 1 ? "" : "s"}`, options: { fontSize: 13, align: "right", fill: { color: hl ? PANEL : CREAM } } },
    { text: note, options: { fontSize: 12, color, bold: hl, fill: { color: hl ? PANEL : CREAM } } }];
  s.addTable([hdr,
    row(c.name, c.cost, c.speed_days, "cheapest, but lands after the buffer is breached", RED, false),
    row(r.name, r.cost, r.speed_days, `recommended: ${VERDICT_LABEL[r.verdict]}`, GREEN, true),
    row(m.name, m.cost, m.speed_days, `~${pct(m.effective_apr, 0)} effective APR, ${VERDICT_LABEL[m.verdict]}`, RED, false),
  ], { x: M, y: 3.55, w: W - 2 * M, colW: [3.9, 2.2, 1.7, 4.23], border: { type: "solid", color: HAIR, pt: 0.75 },
    fontFace: BODY, rowH: 0.42, valign: "middle", color: INK });
  text(s, "The cheapest product arrives too late. The fastest is the most expensive and still leaves her negative. " +
    "Only the recommended one was tested end to end and holds.",
  { x: M, y: 5.65, w: W - 2 * M, h: 0.7, fontSize: 14, italic: true, color: GREY, lineSpacingMultiple: 1.05 });
  s.addNotes("An early version of our own engine got this wrong. We separated the two questions, then added simulation-based verification.");
}

/* 9. What-if ---------------------------------------------------------------------------- */
{
  const s = slide(CREAM, "What-if simulator", "Test a decision [before] you commit to it");
  const ch = W_IF.chart;
  lineChart(s, [
    { name: "Today's projection", labels: ch.baseline.map((p) => p[0]), values: ch.baseline.map((p) => Math.round(p[1])) },
    { name: ch.label, labels: ch.scenario.map((p) => p[0]), values: ch.scenario.map((p) => Math.round(p[1])) },
  ], { x: M - 0.1, y: 1.75, w: 6.9, h: 3.9, title: `Baseline vs "${ch.label}" (EUR)`, chartColors: [SOFT, ORANGE],
    showLegend: true, legendPos: "b", legendFontSize: 11, legendColor: GREY });

  text(s, `STARTING FROM A LOW POINT OF ${eur(W_IF.trough_before)}`, { x: 7.35, y: 1.85, w: 5.3, h: 0.3, fontSize: 11, bold: true, color: GREY, charSpacing: 1 });
  W_IF.rows.forEach((r, i) => {
    const y = 2.3 + i * 0.78;
    s.addShape(pres.ShapeType.line, { x: 7.35, y: y - 0.08, w: 5.33, h: 0, line: { color: HAIR, width: 0.75 } });
    text(s, r.label, { x: 7.35, y, w: 5.3, h: 0.32, fontSize: 13.5, bold: true });
    text(s, `${VERDICT_LABEL[r.verdict]}  ·  low point ${eur(r.trough_after)}`, { x: 7.35, y: y + 0.32, w: 5.3, h: 0.3, fontSize: 12.5, color: VERDICT_COLOR[r.verdict] });
  });
  text(s, [
    { text: "Honest by construction: ", options: { bold: true } },
    { text: "money can't arrive before the product can be arranged, only products she qualifies for are simulated, and every assumption is stated. It projects only and changes nothing." },
  ], { x: M, y: 5.95, w: W - 2 * M, h: 0.75, fontSize: 13.5, lineSpacingMultiple: 1.05 });
  s.addNotes("Live demo moment: run 'what if I pay the supplier 3 weeks late?' in the chat, then the same in the panel.");
}

/* 10. Security (tiers + the planted attack) ----------------------------------------------- */
{
  const s = slide(INK, "Security", "The agent cannot [move money.] By construction.");
  text(s, "We assume the model can be fully compromised. Every control that matters still holds.",
    { x: M, y: 1.72, w: 11.5, h: 0.4, fontSize: 14, color: SOFT });
  [["T0", "Read", "Read simulated data. No side effects."],
    ["T1", "Recommend", "Forecasts, matches, what-ifs. Every session starts here."],
    ["T2", "Act", "Only if the user switches it on. Even then it prepares a confirmation and stops."]]
    .forEach(([t, n, d], i) => {
      const y = 2.35 + i * 1.0;
      s.addShape(pres.ShapeType.rect, { x: M, y, w: 6.0, h: 0.85, fill: { color: i === 2 ? "2A2620" : "1E1C19" }, line: { color: "3A362F", width: 0.75 } });
      text(s, t, { x: M + 0.25, y: y + 0.17, w: 0.8, h: 0.5, fontFace: HEAD, fontSize: 22, color: i === 2 ? ORANGE : CREAM });
      text(s, n, { x: M + 1.1, y: y + 0.1, w: 4.6, h: 0.32, fontSize: 14, bold: true, color: CREAM });
      text(s, d, { x: M + 1.1, y: y + 0.42, w: 4.75, h: 0.36, fontSize: 12, color: SOFT });
    });

  text(s, "WE PLANTED A REAL ATTACK IN OUR OWN LEDGER", { x: 7.05, y: 2.35, w: 5.6, h: 0.3, fontSize: 11, bold: true, color: ORANGE, charSpacing: 1.2 });
  s.addShape(pres.ShapeType.rect, { x: 7.05, y: 2.72, w: 5.63, h: 1.45, fill: { color: "1E1C19" }, line: { color: ORANGE, width: 1 } });
  text(s, `"${F.planted_attack}"`, { x: 7.25, y: 2.82, w: 5.25, h: 1.28, fontFace: MONO, fontSize: 10.5, color: CREAM, lineSpacingMultiple: 1.0, valign: "middle" });
  text(s, [
    { text: "Detected ", options: { bold: true, color: CREAM } },
    { text: `in ${F.security.languages.length} languages, including disguised spellings. `, options: { color: SOFT } },
    { text: "Redacted ", options: { bold: true, color: CREAM } },
    { text: "while \"please gift wrap\" survives. ", options: { color: SOFT } },
    { text: "Reported ", options: { bold: true, color: CREAM } },
    { text: "to the seller as a security event.", options: { color: SOFT } },
  ], { x: 7.05, y: 4.32, w: 5.63, h: 0.95, fontSize: 12.5, lineSpacingMultiple: 1.05, valign: "top" });

  s.addShape(pres.ShapeType.rect, { x: M, y: 5.55, w: W - 2 * M, h: 1.15, fill: { color: ORANGE }, line: { type: "none" } });
  text(s, [
    { text: "confirm_action is not a registered agent tool.", options: { bold: true, breakLine: true } },
    { text: "A fully prompt-injected model has nothing to call. Tokens are single-use, expire, and are bound to exactly what the human saw. Each session reads only its own audit records." },
  ], { x: M + 0.35, y: 5.67, w: W - 2 * M - 0.7, h: 0.95, fontSize: 13, color: INK, lineSpacingMultiple: 1.05, valign: "middle" });
  s.addNotes("Pattern matching does not solve prompt injection and we don't claim it does. The permission model bounds the damage: " +
    "an injection can waste a turn, but it can't move money. Full detail is in the appendix and docs/SECURITY.md.");
}

/* 11. Accuracy --------------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Evidence", "How accurate is it? Two [honest] numbers.");
  text(s, "A backtest on data that matches the model's own assumptions only proves consistency. So we broke the assumptions on purpose and measured again.",
    { x: M, y: 1.72, w: 11.6, h: 0.55, fontSize: 14, color: GREY, lineSpacingMultiple: 1.05 });
  big(s, { x: M, y: 2.45, w: 4.6, size: 54, value: `${A.consistency_mean_pct}%`,
    label: "consistency check: mean error on data that matches the model's assumptions" });
  big(s, { x: M, y: 4.2, w: 4.6, size: 54, value: `${stress("late_payouts").mean_pct}%`, color: ORANGE,
    label: "when payouts arrive 0-3 days late: the real weak spot, published" });
  const rows = A.stress.results;
  s.addChart(pres.ChartType.bar, [{ name: "Mean forecast error", labels: rows.map((r) => r.label.replace("Marketplace p", "P").replace(" at random", "")),
    values: rows.map((r) => r.mean_pct) }], {
    x: 5.5, y: 2.35, w: 7.2, h: 3.4, barDir: "bar", showTitle: true, title: "Mean error under stress, % of monthly revenue",
    titleFontSize: 12, titleColor: GREY, titleFontFace: BODY, chartColors: [INK],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelColor: GREY,
    dataLabelFormatCode: '0.0"%"', showLegend: false, catAxisLabelColor: GREY, catAxisLabelFontSize: 10.5,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    plotArea: { fill: { color: CREAM } }, chartArea: { fill: { color: CREAM } },
  });
  text(s, [
    { text: "Turned into a feature: ", options: { bold: true } },
    { text: "the what-if simulator lets a seller test late payouts on their own projection instead of trusting one number.  " },
    { text: `${F.counts.tests} tests · ${F.counts.transactions.toLocaleString("en-US")} simulated transactions · reproducible from the repository.`, options: { color: GREY } },
  ], { x: M, y: 6.0, w: W - 2 * M, h: 0.7, fontSize: 13, lineSpacingMultiple: 1.05 });
}

/* 12. Who deploys this ------------------------------------------------------------------- */
{
  const s = slide(CREAM, "Relevance", "Who deploys this, and [why they would]");
  text(s, "A micro-business will not buy a finance tool. It will use the one inside the bank or marketplace it already has.",
    { x: M, y: 1.72, w: 11.6, h: 0.45, fontSize: 14, color: GREY });
  panel(s, M, 2.35, 4.35, 3.55, INK);
  text(s, "THE SCALE IS ALREADY THERE", { x: M + 0.3, y: 2.55, w: 3.9, h: 0.25, fontSize: 10.5, bold: true, color: SOFT, charSpacing: 1.2 });
  big(s, { x: M + 0.3, y: 2.85, w: 3.8, size: 34, value: compact(mk("webank_micro_enterprises")), color: ORANGE,
    label: "small and micro enterprises served by WeBank, end of 2025", labelColor: SOFT });
  big(s, { x: M + 0.3, y: 4.1, w: 3.8, size: 34, value: compact(mk("webank_individual_customers")), color: CREAM,
    label: "individual customers, same date", labelColor: SOFT });
  text(s, [{ text: "Stated aim: ", options: { bold: true } }, { text: `"${MK.quotes.webank_mission.text}"`, options: { italic: true } }],
    { x: M + 0.3, y: 5.3, w: 3.8, h: 0.55, fontSize: 10.5, color: SOFT, lineSpacingMultiple: 1.0, valign: "top" });

  [["Fewer bad loans", "Free options first, repayments simulated before any product. A business that should not borrow is told so, in its own numbers."],
    ["Advice at the cost of a tool call", "A relationship manager per micro-business does not scale. A forecast, an explained rejection and a simulator do."],
    ["An AI a supervisor can inspect", "Permission tiers, human-only confirmation, and a hash-chained record of every decision. Deployable, not just interesting."]]
    .forEach(([t, d], i) => {
      const y = 2.35 + i * 1.2;
      s.addShape(pres.ShapeType.line, { x: 5.45, y, w: 7.23, h: 0, line: { color: HAIR, width: 0.75 } });
      num(s, 5.45, y + 0.12, i + 1);
      text(s, t, { x: 6.2, y: y + 0.14, w: 6.4, h: 0.34, fontFace: HEAD, fontSize: 15 });
      text(s, d, { x: 6.2, y: y + 0.5, w: 6.45, h: 0.62, fontSize: 12.5, color: GREY, lineSpacingMultiple: 1.0, valign: "top" });
    });
  text(s, [
    { text: "The mechanic travels: ", options: { bold: true } },
    { text: "a payout hold is a payout hold in Shenzhen, Jakarta or Berlin. Between markets only the product catalog and the currency change, and both are data files, not code." },
  ], { x: M, y: 6.1, w: W - 2 * M, h: 0.7, fontSize: 13.5, lineSpacingMultiple: 1.05 });
  s.addNotes("WeBank figures are WeBank's own, from its March 2026 release, and are in data/market.json with the link. " +
    "The point is distribution: we are an advisory layer an institution can deploy, not a lender competing with one.");
}

/* 13. Close --------------------------------------------------------------------------------- */
{
  const s = slide(INK, null, null);
  s.addText(runs("AN AI PARTICIPANT THAT KNOWS WHAT IT [MUST NOT DO]", CREAM, ORANGE), { x: M, y: 1.5, w: 11.5, h: 2.0, isTextBox: true, margin: 0,
    fontFace: HEAD, fontSize: 44, valign: "top", lineSpacingMultiple: 0.95 });
  text(s, "It finds the cash gap before it happens, tests every option before recommending it, and is structurally incapable of acting without your approval.",
    { x: M, y: 3.75, w: 10.5, h: 0.9, fontSize: 17, color: SOFT, lineSpacingMultiple: 1.1 });
  const y = 5.35;
  s.addShape(pres.ShapeType.line, { x: M, y, w: 12.03, h: 0, line: { color: SOFT, width: 1.5 } });
  s.addShape(pres.ShapeType.ellipse, { x: M + 12.03 - 0.18, y: y - 0.18, w: 0.36, h: 0.36, fill: { color: ORANGE }, line: { type: "none" } });
  text(s, "MARKETPLACE", { x: M, y: y - 0.45, w: 2.5, h: 0.25, fontSize: 10.5, bold: true, color: SOFT, charSpacing: 1.5 });
  text(s, "BANK", { x: 11.0, y: y - 0.48, w: 1.4, h: 0.25, fontSize: 10.5, bold: true, color: ORANGE, charSpacing: 1.5, align: "right" });
  pill(s, "SIMULATED DATA THROUGHOUT. NOT FINANCIAL ADVICE.", M, 5.95, 5.4, ORANGE, INK);
  text(s, "THANK YOU", { x: 8.6, y: 5.9, w: 4.08, h: 0.45, fontFace: HEAD, fontSize: 22, color: CREAM, align: "right" });
}

/* Appendix A1. Honest rejection -------------------------------------------------------------- */
{
  const s = slide(CREAM, "Appendix  ·  Trust", "Saying no, [usefully]", { appendix: "APPENDIX A1" });
  text(s, "Lina's Ceramics  ·  Lisbon", { x: M, y: 1.9, w: 6, h: 0.3, fontSize: 12.5, bold: true, color: ORANGE_TXT });
  text(s, `${L.months_trading} months trading. ${pct(L.refund_rate)} refund rate. Most commercial products are out of reach.`,
    { x: M, y: 2.25, w: 5.8, h: 0.8, fontFace: HEAD, fontSize: 16, lineSpacingMultiple: 1.0, valign: "top" });
  const nm = L.near_miss.slice(0, 2).map((n) => {
    const w = n.why_not[0];
    return { text: `${n.name}: needs ${w.required} ${w.label.toLowerCase().replace(/^(minimum|maximum) /, "")}, she has ${w.actual}`, options: { bullet: { indent: 14 }, breakLine: true } };
  });
  text(s, [{ text: "It names exactly what she narrowly misses:", options: { breakLine: true, italic: true } }].concat(nm).concat([
    { text: `Available now: two microloans from ${eur(L.cheapest_cost)}`, options: { bullet: { indent: 14 } } }]),
  { x: M, y: 3.2, w: 5.8, h: 2.0, fontSize: 13, color: GREY, paraSpaceAfter: 6, lineSpacingMultiple: 1.05, valign: "top" });

  panel(s, 6.9, 1.9, 5.78, 3.6, INK);
  text(s, "WHY THIS MATTERS COMMERCIALLY", { x: 7.2, y: 2.12, w: 5.2, h: 0.3, fontSize: 11, bold: true, color: ORANGE, charSpacing: 1.2 });
  text(s, [
    { text: "Every rejection names the test that failed, the gap, and what would change it.", options: { bullet: { indent: 14 }, breakLine: true } },
    { text: "A seller who can't borrow today learns what to fix, and comes back when they can.", options: { bullet: { indent: 14 }, breakLine: true } },
    { text: "Grants are shown but excluded: they can't be spent as working capital, and the copilot says so instead of padding the list.", options: { bullet: { indent: 14 } } },
  ], { x: 7.2, y: 2.55, w: 5.2, h: 2.8, fontSize: 13.5, color: CREAM, paraSpaceAfter: 8, lineSpacingMultiple: 1.05, valign: "top" });
  text(s, "The copilot never says \"approved\". It matches published criteria, and a lender decides. An output guardrail enforces that, not just a prompt.",
    { x: M, y: 5.85, w: W - 2 * M, h: 0.6, fontSize: 13.5, italic: true, color: GREY });
}

/* Appendix A2. Prompt injection, in full -------------------------------------------------- */
{
  const s = slide(CREAM, "Appendix  ·  Security", "We attacked our [own product]", { appendix: "APPENDIX A2" });
  text(s, "A financial copilot reads fields the seller doesn't control. Anyone who can place an order can write text aimed at the model, so we planted a real attack in the sandbox ledger.",
    { x: M, y: 1.72, w: 11.6, h: 0.65, fontSize: 14, color: GREY, lineSpacingMultiple: 1.05 });
  panel(s, M, 2.5, W - 2 * M, 1.2, INK);
  text(s, "CUSTOMER ORDER NOTE, LIVE IN OUR DATASET", { x: M + 0.3, y: 2.62, w: 8, h: 0.25, fontSize: 10.5, bold: true, color: ORANGE, charSpacing: 1.2 });
  text(s, `"${F.planted_attack}"`, { x: M + 0.3, y: 2.92, w: 11.4, h: 0.7, fontFace: MONO, fontSize: 11, color: CREAM, lineSpacingMultiple: 1.0 });
  [["Detect", `Attacks in ${F.security.languages.length} languages (${F.security.languages.join(", ")}), including disguised spellings like "I-g-n-o-r-e".`],
    ["Neutralise", "The attack is redacted and the rest fenced as untrusted data. \"Please gift wrap\" survives. The attack doesn't."],
    ["Report", "The seller is told once per session. It's a security event on their account."]]
    .forEach(([n, d], i) => {
      const y = 3.95 + i * 0.75;
      s.addShape(pres.ShapeType.line, { x: M, y: y - 0.08, w: W - 2 * M, h: 0, line: { color: HAIR, width: 0.75 } });
      num(s, M, y, i + 1);
      text(s, n, { x: M + 0.75, y: y + 0.05, w: 2.0, h: 0.4, fontFace: HEAD, fontSize: 15 });
      text(s, d, { x: 3.1, y: y + 0.06, w: 9.55, h: 0.55, fontSize: 13, color: GREY, valign: "top" });
    });
  text(s, "Pattern matching doesn't solve prompt injection, and we don't claim it does. The permission model bounds the damage: an injection can waste a turn, but it can't move money.",
    { x: M, y: 6.25, w: W - 2 * M, h: 0.6, fontSize: 13, italic: true, color: ORANGE_TXT });
}

/* Appendix A3. Scoring fit ------------------------------------------------------------------ */
{
  const s = slide(CREAM, "Appendix  ·  Fit", "Built against the [marking scheme]", { appendix: "APPENDIX A3" });
  const h = (t, o) => ({ text: t, options: Object.assign({ bold: true, color: CREAM, fontSize: 12, fill: { color: INK } }, o || {}) });
  const c = (t, o) => ({ text: t, options: Object.assign({ fontSize: 13, color: GREY, fill: { color: CREAM } }, o || {}) });
  s.addTable([
    [h("Criterion"), h("Weight", { align: "center" }), h("How this entry addresses it")],
    [c("Task completion", { bold: true, color: INK }), c("40%", { bold: true, color: ORANGE_TXT, fontSize: 15, align: "center" }),
      c(`All three required capabilities plus a what-if simulator, working end to end, with ${F.counts.tests} tests and an evidence pack of ${F.counts.evidence_scenarios} scenarios.`)],
    [c("Security & compliance", { bold: true, color: INK }), c("30%", { bold: true, color: ORANGE_TXT, fontSize: 15, align: "center" }),
      c(`Advice-only by default, human-only confirmation, injection defence in ${F.security.languages.length} languages, per-session audit access, and a self-assessment with ${F.security.known_risks} known risks.`)],
    [c("Innovation & interaction", { bold: true, color: INK }), c("30%", { bold: true, color: ORANGE_TXT, fontSize: 15, align: "center" }),
      c("Two-ledger cash model, lead time separated from duration, every recommendation tested by simulation, and rejections that explain themselves.")],
  ], { x: M, y: 1.95, w: W - 2 * M, colW: [2.9, 1.3, 7.83], border: { type: "solid", color: HAIR, pt: 0.75 },
    fontFace: BODY, rowH: 0.8, valign: "middle" });
  panel(s, M, 5.55, W - 2 * M, 1.05, INK);
  text(s, [
    { text: "No contradictions, enforced: ", options: { bold: true, color: ORANGE } },
    { text: "every figure in this deck and the documentation comes from one facts file generated by the system, and the test suite fails if any document quotes a stale number.", options: { color: CREAM } },
  ], { x: M + 0.35, y: 5.65, w: W - 2 * M - 0.7, h: 0.85, fontSize: 13.5, lineSpacingMultiple: 1.05, valign: "middle" });
}

pres.writeFile({ fileName: OUT }).then(() => console.log("wrote " + path.resolve(OUT)));
