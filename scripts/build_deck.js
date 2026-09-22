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
const F = JSON.parse(fs.readFileSync(FACTS_FILE, "utf8"));
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

// ---- palette & type ---------------------------------------------------------
const INK = "16323A", TEAL = "028090", SEA = "00A896", MINT = "02C39A";
const SAND = "F4F6F6", WHITE = "FFFFFF", MUTED = "5C6B70", CRIT = "B3261E", WARN = "9A6100";
const GREEN = "16794A";
const HEAD = "Cambria", BODY = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Fintechathon International Track - Topic E";
pres.title = "SME Finance Copilot";
const W = 13.3, M = 0.7;

// ---- helpers ------------------------------------------------------------------
function darkSlide() { const s = pres.addSlide(); s.background = { color: INK }; return s; }

function lightSlide(title, kicker) {
  const s = pres.addSlide();
  s.background = { color: WHITE };
  s.addText(kicker.toUpperCase(), {
    x: M, y: 0.42, w: W - 2 * M, h: 0.26, isTextBox: true, margin: 0,
    fontFace: BODY, fontSize: 11, bold: true, color: TEAL, charSpacing: 1.6,
  });
  s.addText(title, {
    x: M, y: 0.72, w: W - 2 * M, h: 0.78, isTextBox: true, margin: 0,
    fontFace: HEAD, fontSize: 32, bold: true, color: INK,
  });
  return s;
}

function card(s, { x, y, w, h, fill }) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.1, fill: { color: fill || SAND },
    line: { color: "E1E8E9", width: 0.75 },
    shadow: { type: "outer", angle: 90, blur: 10, offset: 2, color: "9FB4B8", opacity: 0.35 },
  });
}

function iconCircle(s, x, y, glyph, color) {
  const d = 0.52;
  s.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: color || TEAL }, line: { color: color || TEAL, width: 0 } });
  s.addText(glyph, { x, y, w: d, h: d, isTextBox: true, align: "center", valign: "middle",
    fontFace: BODY, fontSize: 17, bold: true, color: WHITE, margin: 0 });
}

function stat(s, { x, y, w, value, label, color, size }) {
  s.addText(value, { x, y, w, h: 0.62, isTextBox: true, margin: 0,
    fontFace: HEAD, fontSize: size || 30, bold: true, color: color || TEAL });
  s.addText(label, { x, y: y + 0.6, w, h: 0.5, isTextBox: true, margin: 0,
    fontFace: BODY, fontSize: 12, color: MUTED, lineSpacing: 15 });
}

function text(s, t, opts) {
  s.addText(t, Object.assign({ isTextBox: true, margin: 0, fontFace: BODY, fontSize: 13, color: INK }, opts));
}

function lineChart(s, series, opts) {
  s.addChart(pres.ChartType.line, series, Object.assign({
    showTitle: true, titleFontSize: 13, titleColor: INK, titleFontFace: BODY,
    lineSize: 2.5, lineSmooth: false, showValue: false,
    catAxisLabelColor: MUTED, catAxisLabelFontSize: 9,
    valAxisLabelColor: MUTED, valAxisLabelFontSize: 9, valAxisLabelFormatCode: "#,##0",
    valGridLine: { color: "EDF1F1", size: 1 }, catGridLine: { style: "none" },
  }, opts));
}

const VERDICT_COLOR = { fixes: GREEN, avoids_negative: GREEN, improves: WARN,
  no_effect: MUTED, worsens: CRIT, breaks: CRIT };
const VERDICT_LABEL = { fixes: "fixes it", avoids_negative: "stays out of the red",
  improves: "still goes negative", no_effect: "no effect", worsens: "makes it worse",
  breaks: "breaks it" };

/* 1. Title ---------------------------------------------------------------- */
{
  const s = darkSlide();
  text(s, "SME Finance Copilot", { x: M, y: 2.25, w: 9.4, h: 1.0, fontFace: HEAD, fontSize: 46, bold: true, color: WHITE });
  text(s, "An AI finance copilot for e-commerce micro-sellers", { x: M, y: 3.28, w: 9.6, h: 0.5, fontSize: 19, color: MINT });
  text(s, "Small online shops miss supplier payments while their money sits in a marketplace " +
    "payout queue. This finds the gap, tests the real options, and cannot act without you.",
    { x: M, y: 3.95, w: 8.6, h: 1.0, fontSize: 13.5, color: "BFD4D6", lineSpacing: 20 });
  text(s, "Fintechathon 2026  ·  International Track  ·  Topic E", { x: M, y: 6.2, w: 8, h: 0.35, fontSize: 12, bold: true, color: SEA, charSpacing: 1.2 });
  text(s, "Theme: AI as a Financial Participant  ·  All data simulated", { x: M, y: 6.56, w: 8, h: 0.35, fontSize: 11, color: MUTED });
  s.addShape(pres.ShapeType.ellipse, { x: 10.15, y: 2.05, w: 2.5, h: 2.5, fill: { color: TEAL, transparency: 55 }, line: { color: TEAL, width: 0 } });
  s.addShape(pres.ShapeType.ellipse, { x: 10.6, y: 2.5, w: 1.6, h: 1.6, fill: { color: MINT }, line: { color: MINT, width: 0 } });
  text(s, eur(H.platform_balance).replace(" ", "\n"), { x: 10.6, y: 2.5, w: 1.6, h: 1.6, align: "center", valign: "middle", fontFace: HEAD, fontSize: 16, bold: true, color: INK });
  text(s, "earned, but unspendable", { x: 9.95, y: 4.62, w: 2.9, h: 0.3, align: "center", fontSize: 10.5, italic: true, color: "BFD4D6" });
  s.addNotes("One line: small online sellers can have money left over every month and still be illiquid, " +
    "because marketplaces hold their money. The agent finds the gap, tests every option by simulation, " +
    "and is architecturally unable to act without human approval. Everything runs on simulated data.");
}

/* 2. The problem ---------------------------------------------------------- */
{
  const s = lightSlide("Money left over every month. About to miss a payment.", "The problem");
  card(s, { x: M, y: 1.85, w: 6.05, h: 3.2 });
  text(s, `${H.name}  ·  Berlin  ·  print-on-demand apparel`, { x: M + 0.35, y: 2.1, w: 5.4, h: 0.3, fontSize: 11.5, bold: true, color: TEAL });
  stat(s, { x: M + 0.35, y: 2.52, w: 2.65, value: eur(H.monthly_revenue), label: "monthly revenue" });
  stat(s, { x: M + 3.15, y: 2.52, w: 2.5, value: eur(H.monthly_cash_surplus), label: "left over monthly, after all\nregular payments incl. loan" });
  stat(s, { x: M + 0.35, y: 3.78, w: 2.65, value: eur(H.bank_balance), label: "in the bank today" });
  stat(s, { x: M + 3.15, y: 3.78, w: 2.5, value: eur(H.bill_amount), label: `stock bill due ${day(H.bill_due)}`, color: CRIT });

  card(s, { x: 7.15, y: 1.85, w: 5.45, h: 3.2, fill: "FDECEA" });
  iconCircle(s, 7.5, 2.15, "!", CRIT);
  text(s, "She can't pay it on time", { x: 8.15, y: 2.18, w: 4.2, h: 0.4, fontFace: HEAD, fontSize: 19, bold: true, color: CRIT });
  text(s, [
    { text: "She isn't badly run. She is illiquid.", options: { breakLine: true, bold: true } },
    { text: `${eur(H.platform_balance)} of her own money is already earned, waiting in the marketplace payout queue.`, options: { bullet: true, breakLine: true } },
    { text: `Payouts run every ${H.payout_cadence_days} days, after a ${H.payout_hold_days}-day hold.`, options: { bullet: true, breakLine: true } },
    { text: `That's ${H.trapped_days} days of sales she can't touch.`, options: { bullet: true } },
  ], { x: 7.5, y: 2.8, w: 4.7, h: 2.05, paraSpaceAfter: 7, lineSpacing: 18 });

  text(s, "Her bank app shows a balance and her accountant sees a year of profit. " +
    `Neither tells her she goes negative on ${day(H.first_negative_date)}.`,
    { x: M, y: 5.35, w: W - 2 * M, h: 0.55, fontSize: 14, italic: true, color: MUTED });
  s.addNotes("'Left over after all regular payments' is deliberate wording: it includes her loan " +
    "repayment, which is a cash outflow but not an accounting expense - so it is not called profit.");
}

/* 3. Why this niche -------------------------------------------------------- */
{
  const s = lightSlide("Why e-commerce micro-sellers", "Focus");
  const rows = [
    ["1", "The pain is structural, not occasional", "Every marketplace holds funds. The squeeze comes back at every seasonal stock purchase, for every seller, by design."],
    ["2", "Underbanked by traditional lenders", "Short trading history and no collateral. The fast money they're offered is often a merchant cash advance with a very high effective rate."],
    ["3", "Their data is transaction-shaped", "Orders, fees, refunds, payouts. That makes realistic modelling possible, and so an honest demo."],
  ];
  let y = 1.95;
  rows.forEach(([n, t, d]) => {
    card(s, { x: M, y, w: W - 2 * M, h: 1.28 });
    iconCircle(s, M + 0.4, y + 0.38, n, TEAL);
    text(s, t, { x: M + 1.15, y: y + 0.22, w: 10.6, h: 0.38, fontFace: HEAD, fontSize: 17, bold: true });
    text(s, d, { x: M + 1.15, y: y + 0.63, w: 10.6, h: 0.5, color: MUTED, lineSpacing: 17 });
    y += 1.5;
  });
  text(s, "Positioning: an independent advisor on the seller's side, not a lender selling its own product.",
    { x: M, y: 6.5, w: W - 2 * M, h: 0.4, fontSize: 12.5, italic: true, color: TEAL });
  s.addNotes("The concept is not new - lenders like Wayflyer or Shopify Capital serve this market. " +
    "They sell their own product. We compare everyone, recommend free options first, and test every option by simulation.");
}

/* 4. Two ledgers --------------------------------------------------------- */
{
  const s = lightSlide("The insight other tools model away", "Core mechanic");
  text(s, "Consumer finance tools model one account. These businesses have two, and the cash-flow crisis happens in the gap between them.",
    { x: M, y: 1.72, w: 11.4, h: 0.5, fontSize: 14, color: MUTED });
  card(s, { x: M, y: 2.4, w: 4.7, h: 2.5, fill: "E6F4F4" });
  iconCircle(s, M + 0.35, 2.7, "P", SEA);
  text(s, "Platform balance", { x: M + 1.05, y: 2.74, w: 3.4, h: 0.36, fontFace: HEAD, fontSize: 17, bold: true });
  text(s, "sales  -  fees  -  refunds  -  payouts", { x: M + 0.35, y: 3.32, w: 4.1, h: 0.32, fontFace: "Courier New", fontSize: 11, color: TEAL });
  text(s, "Money she has earned but can't spend. It is released on the payout schedule, after the hold, minus a rolling reserve.",
    { x: M + 0.35, y: 3.72, w: 4.05, h: 1.0, fontSize: 12.5, color: MUTED, lineSpacing: 17 });
  s.addShape(pres.ShapeType.rightArrow, { x: 5.62, y: 3.42, w: 0.95, h: 0.5, fill: { color: MINT }, line: { color: MINT, width: 0 } });
  text(s, `every ${H.payout_cadence_days}d,\nafter ${H.payout_hold_days}d hold`, { x: 5.35, y: 3.95, w: 1.5, h: 0.55, align: "center", fontSize: 9.5, color: MUTED });
  card(s, { x: 6.75, y: 2.4, w: 4.7, h: 2.5 });
  iconCircle(s, 7.1, 2.7, "B", TEAL);
  text(s, "Bank balance", { x: 7.8, y: 2.74, w: 3.4, h: 0.36, fontFace: HEAD, fontSize: 17, bold: true });
  text(s, "opening  +  payouts  -  expenses", { x: 7.1, y: 3.32, w: 4.1, h: 0.32, fontFace: "Courier New", fontSize: 11, color: TEAL });
  text(s, "The only money that can actually pay a supplier. This is what the forecast projects, day by day.",
    { x: 7.1, y: 3.72, w: 4.05, h: 1.0, fontSize: 12.5, color: MUTED, lineSpacing: 17 });
  card(s, { x: M, y: 5.2, w: W - 2 * M, h: 1.15, fill: "E8F8F3" });
  text(s, [
    { text: "Modelling both ledgers lets the copilot say: " },
    { text: `"you're short because ${H.trapped_days} days of your sales are locked in a queue"`, options: { bold: true, italic: true } },
    { text: ". That's a cause, not just a number." },
  ], { x: M + 0.35, y: 5.42, w: 11.5, h: 0.75, fontSize: 14, lineSpacing: 20 });
}

/* 5. Four capabilities ---------------------------------------------------- */
{
  const s = lightSlide("What it does", "Capabilities");
  const items = [
    ["1", "Cash-flow alerts", "Projects the bank balance day by day. Names the payment causing the squeeze, how much is needed, for how long, and how long there is to arrange it.", TEAL],
    ["2", "Financing matching", `${F.counts.products} illustrative products, checked criterion by criterion, then simulated with their real repayments before any is recommended.`, SEA],
    ["3", "Financial analysis", "Contribution margin, break-even, the cash left over each month, peer comparison, and how much money is trapped in the payout queue.", MINT],
    ["4", "What-if simulator", "Pay a bill later, cut ads, payouts arriving late, take a loan. See the effect before you commit. It changes nothing.", GREEN],
  ];
  let x = M;
  items.forEach(([n, t, d, c]) => {
    card(s, { x, y: 1.95, w: 2.83, h: 3.4 });
    iconCircle(s, x + 0.3, 2.28, n, c);
    text(s, t, { x: x + 0.3, y: 2.98, w: 2.3, h: 0.4, fontFace: HEAD, fontSize: 16, bold: true });
    text(s, d, { x: x + 0.3, y: 3.45, w: 2.3, h: 1.8, fontSize: 11.5, color: MUTED, lineSpacing: 15 });
    x += 3.03;
  });
  card(s, { x: M, y: 5.6, w: W - 2 * M, h: 0.95, fill: "F0F4F4" });
  text(s, [
    { text: "The tools do the arithmetic. The model plans and explains. ", options: { bold: true } },
    { text: "Every figure comes from deterministic code, so the whole system runs with no API key, and the judges get the same numbers we do." },
  ], { x: M + 0.35, y: 5.76, w: 11.5, h: 0.65, fontSize: 12.5, lineSpacing: 17 });
}

/* 6. The answer ------------------------------------------------------------- */
{
  const s = lightSlide("What it actually tells her", "Demo");
  lineChart(s, [{ name: "Projected bank balance", labels: H.balance_series.map((p) => p[0]),
    values: H.balance_series.map((p) => Math.round(p[1])) }],
  { x: M, y: 1.8, w: 7.5, h: 3.5, title: "Projected bank balance, next 60 days", chartColors: [TEAL], showLegend: false });

  card(s, { x: 8.5, y: 1.8, w: 4.1, h: 3.5, fill: "FDECEA" });
  text(s, "Goes negative", { x: 8.85, y: 2.02, w: 3.4, h: 0.3, fontSize: 11, bold: true, color: CRIT, charSpacing: 1 });
  text(s, day(H.first_negative_date), { x: 8.85, y: 2.32, w: 3.4, h: 0.45, fontFace: HEAD, fontSize: 24, bold: true, color: CRIT });
  [["Lowest point", `${eur(H.trough_balance)} on ${day(H.trough_date)}`],
    ["Needs", eur(H.need_amount)],
    ["For", `${H.need_days} days`],
    ["Time to arrange it", `${H.lead_days} days`]].forEach(([k, v], i) => {
    const fy = 2.95 + i * 0.42;
    text(s, k, { x: 8.85, y: fy, w: 1.6, h: 0.3, fontSize: 11.5, color: MUTED });
    text(s, v, { x: 10.4, y: fy, w: 1.95, h: 0.3, align: "right", fontSize: 11.5, bold: true });
  });
  text(s, `Cause: ${H.bill_counterparty}, ${eur(H.bill_amount)}`, { x: 8.85, y: 4.78, w: 3.4, h: 0.35, fontSize: 11, italic: true, color: CRIT });

  card(s, { x: M, y: 5.5, w: W - 2 * M, h: 1.1, fill: "E8F8F3" });
  text(s, [
    { text: "It's a timing problem, not a failing business: ", options: { bold: true } },
    { text: `with no action she recovers to ${eur(H.balance_day_60)} by day 60. Before it mentions borrowing, it suggests an early payout request, pausing ads and talking to the supplier, all of them free.` },
  ], { x: M + 0.35, y: 5.68, w: 11.5, h: 0.8, fontSize: 12.5, lineSpacing: 17 });
}

/* 7. Lead time vs duration -------------------------------------------------- */
{
  const s = lightSlide("The distinction a generic assistant gets wrong", "Differentiator");
  text(s, "Two different questions that usually get mixed up. Mixing them up recommends the wrong product with total confidence.",
    { x: M, y: 1.72, w: 11.4, h: 0.45, fontSize: 14, color: MUTED });
  card(s, { x: M, y: 2.3, w: 5.8, h: 1.45, fill: "E6F4F4" });
  text(s, "How long the money is needed FOR", { x: M + 0.35, y: 2.5, w: 5.1, h: 0.32, fontSize: 11.5, bold: true, color: TEAL });
  text(s, `${H.need_days} days`, { x: M + 0.35, y: 2.82, w: 2.4, h: 0.55, fontFace: HEAD, fontSize: 27, bold: true });
  text(s, "drives the cost", { x: M + 2.9, y: 2.98, w: 2.5, h: 0.32, fontSize: 12, italic: true, color: MUTED });
  card(s, { x: 6.8, y: 2.3, w: 5.8, h: 1.45, fill: "FDF5E6" });
  text(s, "How long there is to ARRANGE it", { x: 7.15, y: 2.5, w: 5.1, h: 0.32, fontSize: 11.5, bold: true, color: WARN });
  text(s, `${H.lead_days} days`, { x: 7.15, y: 2.82, w: 2.4, h: 0.55, fontFace: HEAD, fontSize: 27, bold: true });
  text(s, "drives what is possible", { x: 9.6, y: 2.98, w: 2.7, h: 0.32, fontSize: 12, italic: true, color: MUTED });

  const c = H.cheapest_overall, r = H.recommended, m = H.mca;
  const hdr = ["Product", `Cost for ${H.need_days} days`, "Arranges in", "Tested by simulation"].map((t) =>
    ({ text: t, options: { bold: true, color: MUTED, fontSize: 10.5, fill: { color: "F0F4F4" } } }));
  const row = (name, cost, speed, note, color, bold) => [
    { text: name, options: { fontSize: 11.5, bold } },
    { text: eur(cost), options: { fontSize: 11.5, align: "right" } },
    { text: `${speed} day${speed === 1 ? "" : "s"}`, options: { fontSize: 11.5, align: "right" } },
    { text: note, options: { fontSize: 10.5, color, italic: true } }];
  s.addTable([hdr,
    row(c.name, c.cost, c.speed_days, `cheapest, but lands after the buffer is breached`, CRIT, false),
    row(r.name, r.cost, r.speed_days, `recommended: ${VERDICT_LABEL[r.verdict]}`, GREEN, true),
    row(m.name, m.cost, m.speed_days, `~${pct(m.effective_apr, 0)} effective APR, ${VERDICT_LABEL[m.verdict]}`, CRIT, false),
  ], { x: M, y: 4.0, w: W - 2 * M, colW: [3.9, 2.1, 1.7, 4.2], border: { type: "solid", color: "E1E8E9", pt: 0.75 },
    fontFace: BODY, rowH: 0.36, valign: "middle", color: INK });
  text(s, "The cheapest product isn't the answer, because it arrives too late. The fastest one is " +
    "the most expensive and still leaves her negative. Only the recommended one was tested end to end and holds.",
    { x: M, y: 5.95, w: W - 2 * M, h: 0.65, italic: true, color: TEAL, lineSpacing: 18 });
  s.addNotes("An early version of our own engine got this wrong. We separated the two questions, then added simulation-based verification.");
}

/* 8. What-if ----------------------------------------------------------------- */
{
  const s = lightSlide("Test a decision before you commit to it", "What-if simulator");
  const ch = W_IF.chart;
  lineChart(s, [
    { name: "Today's projection", labels: ch.baseline.map((p) => p[0]), values: ch.baseline.map((p) => Math.round(p[1])) },
    { name: ch.label, labels: ch.scenario.map((p) => p[0]), values: ch.scenario.map((p) => Math.round(p[1])) },
  ], { x: M, y: 1.75, w: 6.6, h: 3.6, title: `Baseline vs "${ch.label}"`, chartColors: [TEAL, GREEN],
    showLegend: true, legendPos: "b", legendFontSize: 10, legendColor: MUTED });

  card(s, { x: 7.55, y: 1.75, w: 5.05, h: 3.6 });
  text(s, `Starting from a low point of ${eur(W_IF.trough_before)}`, { x: 7.85, y: 1.92, w: 4.5, h: 0.3, fontSize: 11.5, bold: true, color: MUTED });
  W_IF.rows.forEach((r, i) => {
    const y = 2.35 + i * 0.73;
    text(s, r.label, { x: 7.85, y, w: 4.5, h: 0.3, fontSize: 12.5, bold: true });
    text(s, `${VERDICT_LABEL[r.verdict]}  ·  low point ${eur(r.trough_after)}`, { x: 7.85, y: y + 0.3, w: 4.5, h: 0.3, fontSize: 11.5, color: VERDICT_COLOR[r.verdict] });
  });
  card(s, { x: M, y: 5.6, w: W - 2 * M, h: 1.0, fill: "E8F8F3" });
  text(s, [
    { text: "Honest by construction: ", options: { bold: true } },
    { text: "money can't arrive before the product can be arranged, only products she qualifies for can be simulated, and every assumption is stated. It projects only and changes nothing." },
  ], { x: M + 0.35, y: 5.76, w: 11.5, h: 0.7, fontSize: 12.5, lineSpacing: 17 });
  s.addNotes("Live demo moment: run 'what if I pay the supplier 3 weeks late?' in the chat, then the same in the panel.");
}

/* 9. Honest rejection --------------------------------------------------------- */
{
  const s = lightSlide("Saying no, usefully", "Trust");
  card(s, { x: M, y: 1.9, w: 5.85, h: 3.4 });
  text(s, "Lina's Ceramics  ·  Lisbon", { x: M + 0.35, y: 2.12, w: 5.1, h: 0.3, fontSize: 11.5, bold: true, color: TEAL });
  text(s, `${L.months_trading} months trading. ${pct(L.refund_rate)} refund rate. Most commercial products are out of reach.`,
    { x: M + 0.35, y: 2.45, w: 5.15, h: 0.68, fontFace: HEAD, fontSize: 15.5, bold: true, lineSpacing: 21 });
  const nm = L.near_miss.slice(0, 2).map((n) => {
    const w = n.why_not[0];
    return { text: `${n.name}: needs ${w.required} ${w.label.toLowerCase().replace(/^(minimum|maximum) /, "")}, she has ${w.actual}`, options: { bullet: true, breakLine: true } };
  });
  text(s, [{ text: "It names exactly what she narrowly misses:", options: { breakLine: true, italic: true } }].concat(nm).concat([
    { text: `Available now: two microloans from ${eur(L.cheapest_cost)}`, options: { bullet: true } }]),
  { x: M + 0.35, y: 3.25, w: 5.15, h: 1.9, fontSize: 12, color: MUTED, paraSpaceAfter: 6, lineSpacing: 16 });

  card(s, { x: 6.9, y: 1.9, w: 5.7, h: 3.4, fill: "E8F8F3" });
  iconCircle(s, 7.25, 2.2, "?", SEA);
  text(s, "Why this matters commercially", { x: 7.95, y: 2.24, w: 4.4, h: 0.36, fontFace: HEAD, fontSize: 17, bold: true });
  text(s, [
    { text: "Every rejection names the test that failed, the gap, and what would change it.", options: { bullet: true, breakLine: true } },
    { text: "A seller who can't borrow today learns what to fix, and comes back when they can.", options: { bullet: true, breakLine: true } },
    { text: "Grants are shown but excluded here: they can't be spent as working capital, and the copilot says so instead of padding the list.", options: { bullet: true } },
  ], { x: 7.25, y: 2.85, w: 5.0, h: 2.25, fontSize: 12.5, paraSpaceAfter: 8, lineSpacing: 17 });
  text(s, "The copilot never says \"approved\". It matches published criteria, and a lender decides. That rule is enforced by an output guardrail, not just a prompt.",
    { x: M, y: 5.55, w: W - 2 * M, h: 0.6, italic: true, color: MUTED, lineSpacing: 18 });
}

/* 10. Security core ------------------------------------------------------------ */
{
  const s = darkSlide();
  text(s, "SECURITY", { x: M, y: 0.55, w: 6, h: 0.28, fontSize: 11, bold: true, color: MINT, charSpacing: 1.6 });
  text(s, "The agent cannot move money. By construction.", { x: M, y: 0.9, w: 11.6, h: 0.75, fontFace: HEAD, fontSize: 31, bold: true, color: WHITE });
  text(s, "We assume the model can be fully compromised. Every control that matters still holds under that assumption.",
    { x: M, y: 1.75, w: 11.3, h: 0.5, fontSize: 13.5, color: "BFD4D6" });
  [["T0", "Read", "Read simulated data. No side effects.", "3A5A62"],
    ["T1", "Recommend", "Analysis, forecasts, matches, what-ifs. No side effects. Every session starts here.", "046C7A"],
    ["T2", "Act", "Only if the user switches it on. Even then it never executes: it prepares a confirmation and stops.", "9A6100"]]
    .forEach(([t, n, d, fill], i) => {
      const ty = 2.5 + i * 0.98;
      s.addShape(pres.ShapeType.roundRect, { x: M, y: ty, w: 11.9, h: 0.82, rectRadius: 0.08, fill: { color: fill }, line: { color: fill, width: 0 } });
      text(s, t, { x: M + 0.3, y: ty + 0.19, w: 0.7, h: 0.44, fontFace: HEAD, fontSize: 19, bold: true, color: WHITE });
      text(s, n, { x: M + 1.1, y: ty + 0.2, w: 2.2, h: 0.42, fontSize: 15, bold: true, color: WHITE });
      text(s, d, { x: M + 3.3, y: ty + 0.24, w: 8.3, h: 0.4, fontSize: 12.5, color: "E4EEEF" });
    });
  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.55, w: 11.9, h: 1.3, rectRadius: 0.08, fill: { color: MINT }, line: { color: MINT, width: 0 } });
  text(s, [
    { text: "confirm_action is not a registered agent tool.", options: { bold: true, breakLine: true } },
    { text: "A fully prompt-injected model has nothing to call. Tokens are single-use, expire, and are bound to exactly what the human was shown. Each session can only read its own audit records." },
  ], { x: M + 0.35, y: 5.7, w: 11.2, h: 1.05, fontSize: 12.5, color: "0B3F38", lineSpacing: 17 });
}

/* 11. Prompt injection ------------------------------------------------------- */
{
  const s = lightSlide("We attacked our own product", "Security");
  text(s, "A financial copilot reads fields the seller doesn't control. Anyone who can place an order can write text aimed at the model, so we planted a real attack in the sandbox ledger.",
    { x: M, y: 1.72, w: 11.5, h: 0.68, fontSize: 13.5, color: MUTED, lineSpacing: 19 });
  card(s, { x: M, y: 2.5, w: W - 2 * M, h: 1.15, fill: "FDECEA" });
  text(s, "Customer order note, live in our dataset", { x: M + 0.32, y: 2.62, w: 8, h: 0.28, fontSize: 10.5, bold: true, color: CRIT });
  text(s, `"${F.planted_attack}"`, { x: M + 0.32, y: 2.92, w: 11.2, h: 0.62, fontFace: "Courier New", fontSize: 10.5, color: "6B1B14", lineSpacing: 15 });
  [["Detect", `Attacks in ${F.security.languages.length} languages (${F.security.languages.join(", ")}), including disguised spellings like "I-g-n-o-r-e".`],
    ["Neutralise", "The attack is redacted and the rest fenced as untrusted data. \"Please gift wrap\" survives. The attack doesn't."],
    ["Report", "The seller is told once per session. It's a security event on their account."]]
    .forEach(([n, d], i) => {
      const ly = 3.85 + i * 0.95;
      card(s, { x: M, y: ly, w: W - 2 * M, h: 0.82 });
      iconCircle(s, M + 0.3, ly + 0.15, String(i + 1), TEAL);
      text(s, n, { x: M + 1.0, y: ly + 0.21, w: 1.7, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true });
      text(s, d, { x: M + 2.7, y: ly + 0.2, w: 8.9, h: 0.45, fontSize: 11.5, color: MUTED, lineSpacing: 15 });
    });
  text(s, "Pattern matching doesn't solve prompt injection, and we don't claim it does. The permission model is what bounds the damage: an injection can waste a turn, but it can't move money.",
    { x: M, y: 6.72, w: W - 2 * M, h: 0.5, fontSize: 12, italic: true, color: TEAL, lineSpacing: 16 });
}

/* 12. Accuracy, honestly ------------------------------------------------------ */
{
  const s = lightSlide("How accurate is it? Two honest numbers.", "Evidence");
  text(s, "A backtest on data that matches the model's own assumptions only proves the model is consistent. So we also broke the assumptions on purpose and measured again.",
    { x: M, y: 1.72, w: 11.5, h: 0.62, fontSize: 13.5, color: MUTED, lineSpacing: 18 });
  const rows = A.stress.results;
  s.addChart(pres.ChartType.bar, [{ name: "Mean forecast error", labels: rows.map((r) => { const t = r.label.replace("Marketplace p", "P").replace(" at random", ""); return t; }),
    values: rows.map((r) => r.mean_pct) }], {
    x: M, y: 2.45, w: 7.9, h: 3.6, barDir: "bar", showTitle: true, title: "Mean error, % of monthly revenue",
    titleFontSize: 12.5, titleColor: INK, titleFontFace: BODY, chartColors: [TEAL],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 9, dataLabelColor: MUTED,
    dataLabelFormatCode: '0.0"%"', showLegend: false, catAxisLabelColor: MUTED, catAxisLabelFontSize: 9.5,
    valAxisLabelColor: MUTED, valAxisLabelFontSize: 9, valAxisLabelFormatCode: '0"%"',
    valGridLine: { color: "EDF1F1", size: 1 }, catGridLine: { style: "none" },
  });
  stat(s, { x: 8.85, y: 2.5, w: 3.8, size: 36, value: `${A.consistency_mean_pct}%`, label: "consistency check: data that matches the model's assumptions" });
  stat(s, { x: 8.85, y: 3.85, w: 3.8, size: 36, value: `${stress("late_payouts").mean_pct}%`, label: "when payouts arrive 0-3 days late: the real weak spot", color: CRIT });
  card(s, { x: 8.85, y: 5.2, w: 3.75, h: 1.45, fill: "FDF5E6" });
  text(s, "Turned into a feature", { x: 9.15, y: 5.35, w: 3.2, h: 0.3, fontSize: 11, bold: true, color: WARN });
  text(s, "The what-if simulator lets a seller test late payouts on their own projection, instead of trusting a single number.",
    { x: 9.15, y: 5.65, w: 3.2, h: 0.9, fontSize: 10.5, color: "6B5200", lineSpacing: 14 });
  text(s, `${F.counts.tests} tests  ·  ${F.counts.transactions.toLocaleString("en-US")} simulated transactions  ·  stress test reproducible from the repository`,
    { x: M, y: 6.3, w: 7.9, h: 0.35, fontSize: 11.5, bold: true, color: TEAL });
}

/* 13. Scoring --------------------------------------------------------------- */
{
  const s = lightSlide("Built against the marking scheme", "Fit");
  const h = (t, o) => ({ text: t, options: Object.assign({ bold: true, color: MUTED, fontSize: 11, fill: { color: "F0F4F4" } }, o || {}) });
  const c = (t, o) => ({ text: t, options: Object.assign({ fontSize: 11.5, color: MUTED }, o || {}) });
  s.addTable([
    [h("Criterion"), h("Weight", { align: "center" }), h("How this entry addresses it")],
    [c("Task completion", { bold: true, color: INK, fontSize: 12 }), c("40%", { bold: true, color: TEAL, fontSize: 13, align: "center" }),
      c(`All three required capabilities plus a what-if simulator, working end to end, with ${F.counts.tests} tests and an evidence pack of ${F.counts.evidence_scenarios} scenarios.`)],
    [c("Security & compliance", { bold: true, color: INK, fontSize: 12 }), c("30%", { bold: true, color: TEAL, fontSize: 13, align: "center" }),
      c(`Advice-only by default, human-only confirmation, injection defence in ${F.security.languages.length} languages, per-session audit access, and a self-assessment with ${F.security.known_risks} known risks.`)],
    [c("Innovation & interaction", { bold: true, color: INK, fontSize: 12 }), c("30%", { bold: true, color: TEAL, fontSize: 13, align: "center" }),
      c("Two-ledger cash model, lead time separated from duration, every recommendation tested by simulation, and rejections that explain themselves.")],
  ], { x: M, y: 1.9, w: W - 2 * M, colW: [2.8, 1.2, 7.9], border: { type: "solid", color: "E1E8E9", pt: 0.75 },
    fontFace: BODY, rowH: 0.72, valign: "middle" });
  card(s, { x: M, y: 5.55, w: W - 2 * M, h: 1.1, fill: "E8F8F3" });
  text(s, [
    { text: "No contradictions, enforced: ", options: { bold: true } },
    { text: "every figure in this deck and in the documentation comes from one facts file generated by the system, and the test suite fails if any document quotes a stale number." },
  ], { x: M + 0.35, y: 5.73, w: 11.5, h: 0.8, fontSize: 12.5, lineSpacing: 17 });
}

/* 14. Status & ask ----------------------------------------------------------- */
{
  const s = lightSlide("Where we are, and what we'd value your view on", "Status");
  card(s, { x: M, y: 1.95, w: 5.85, h: 3.9, fill: "E8F8F3" });
  text(s, "Built and working", { x: M + 0.35, y: 2.15, w: 5.1, h: 0.4, fontFace: HEAD, fontSize: 18, bold: true });
  text(s, [
    "Two-ledger forecaster, with its stress test published",
    `${F.counts.products}-product matching, verified by simulation`,
    "Alerts that put free options first",
    "What-if simulator: web panel and plain English",
    "Permission tiers, human-only confirmation",
    `Injection defence in ${F.security.languages.length} languages; scoped audit log`,
    `Web interface, ${F.counts.tests} tests, full documentation`,
  ].map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } })),
  { x: M + 0.35, y: 2.62, w: 5.1, h: 3.0, fontSize: 12.5, paraSpaceAfter: 7, lineSpacing: 16 });
  card(s, { x: 6.9, y: 1.95, w: 5.7, h: 3.9, fill: "FDF5E6" });
  text(s, "Questions for you", { x: 7.25, y: 2.15, w: 5.0, h: 0.4, fontFace: HEAD, fontSize: 18, bold: true });
  text(s, [
    "Is the niche focused enough, or too narrow for the judges?",
    "Is 'cash left over after all regular payments' the right framing for a business audience?",
    "Does the security story land, or is it over-weighted for a 10-minute pitch?",
    "Should the demo lead with the crisis case or the honest-rejection case?",
  ].map((t, i, a) => ({ text: t, options: { bullet: true, breakLine: i < a.length - 1 } })),
  { x: 7.25, y: 2.62, w: 5.0, h: 3.0, fontSize: 12.5, paraSpaceAfter: 9, lineSpacing: 16 });
  text(s, "Submission deadline: 20 October 2026, 23:59 Beijing time", { x: M, y: 6.1, w: 11.9, h: 0.4, fontSize: 13, bold: true, color: CRIT });
  text(s, "Grand final: Shenzhen, 21-23 November. One team member must attend in person.", { x: M, y: 6.48, w: 11.9, h: 0.35, fontSize: 11.5, color: MUTED });
}

/* 15. Close ------------------------------------------------------------------- */
{
  const s = darkSlide();
  text(s, "An AI participant that knows what it must not do", { x: M, y: 2.5, w: 10.4, h: 1.4, fontFace: HEAD, fontSize: 34, bold: true, color: WHITE, lineSpacing: 42 });
  text(s, "It finds the cash gap before it happens, tests every option before recommending it, and is structurally incapable of acting without your approval.",
    { x: M, y: 4.05, w: 9.8, h: 0.9, fontSize: 15, color: "BFD4D6", lineSpacing: 23 });
  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.35, w: 5.4, h: 0.72, rectRadius: 0.08, fill: { color: MINT }, line: { color: MINT, width: 0 } });
  text(s, "Simulated data throughout. Not financial advice.", { x: M + 0.3, y: 5.5, w: 5.0, h: 0.42, fontSize: 12, bold: true, color: "0B3F38" });
  text(s, "Thank you", { x: M, y: 6.35, w: 6, h: 0.45, fontFace: HEAD, fontSize: 20, bold: true, color: SEA });
}

pres.writeFile({ fileName: OUT }).then(() => console.log("wrote " + path.resolve(OUT)));
