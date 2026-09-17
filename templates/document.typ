// Quotation / Proforma template.
//
// This template receives ONLY already-computed figures, passed in as JSON via
// `--input payload`. It performs no arithmetic of its own -- there is no
// addition, no percentage and no rounding anywhere below. Every number printed
// is a string produced by compute.py and cross-checked by recompute.py before
// this file is ever invoked.
//
// The document title comes from `doc.title`, which can only ever be
// "QUOTATION" or "PROFORMA INVOICE" because DocumentType has exactly two
// members. tests/test_no_tax_invoice.py greps this file to keep it that way.

#let data = json(bytes(sys.inputs.payload))

#let ink = rgb("#14161d")
#let muted = rgb("#5e6575")
#let rule = rgb("#d7dbe3")
#let accent = rgb("#1b3a6b")

#set document(title: data.doc.title + " " + data.doc.number, author: data.supplier.name)
#set page(
  paper: "a4",
  margin: (x: 16mm, y: 15mm),
  footer: context [
    #set text(size: 7pt, fill: muted)
    #line(length: 100%, stroke: 0.4pt + rule)
    #v(2pt)
    #grid(
      columns: (1fr, auto),
      align: (left, right),
      [#data.manifest.line],
      [Page #counter(page).display("1 of 1", both: true)],
    )
  ],
)
#set text(font: ("Helvetica Neue", "Helvetica", "Arial"), size: 9pt, fill: ink)
#set par(justify: false, leading: 0.6em)

#let money(s) = text(font: ("Menlo", "Courier New"), size: 8.5pt)[#s]
#let label(s) = text(size: 7pt, fill: muted, weight: "medium", upper(s))

// ---------- header ----------
#grid(
  columns: (1fr, auto),
  align: (left + top, right + top),
  [
    #text(size: 13pt, weight: "bold")[#data.supplier.name]
    #v(3pt)
    #text(size: 8pt, fill: muted)[
      #for l in data.supplier.address [#l \ ]
      #if data.supplier.gstin != none [GSTIN: #data.supplier.gstin \ ]
      #data.supplier.state
      #if data.supplier.email != none [ \ #data.supplier.email]
      #if data.supplier.phone != none [ · #data.supplier.phone]
    ]
  ],
  [
    #text(size: 16pt, weight: "bold", fill: accent)[#data.doc.title]
    #v(4pt)
    #text(size: 8pt)[
      #label("No") #h(4pt) #data.doc.number \
      #label("Date") #h(4pt) #data.doc.issue_date
      #if data.doc.valid_until != none [ \ #label("Valid until") #h(4pt) #data.doc.valid_until]
    ]
  ],
)

#v(6pt)
#line(length: 100%, stroke: 0.8pt + accent)
#v(8pt)

// ---------- parties and supply ----------
#grid(
  columns: (1fr, 1fr),
  gutter: 14pt,
  [
    #label("Quotation for")
    #v(3pt)
    #text(weight: "semibold")[#data.client.name] \
    #text(size: 8pt, fill: muted)[
      #for l in data.client.address [#l \ ]
      #if data.client.gstin != none [GSTIN: #data.client.gstin \ ]
      #if data.client.state != none [#data.client.state]
    ]
  ],
  [
    #label("Place of supply")
    #v(3pt)
    #text(weight: "semibold")[#data.supply.state]
    #h(4pt)
    #text(size: 7.5pt, fill: muted)[(#data.supply.rule)]
    #v(3pt)
    #text(size: 7.5pt, fill: muted)[#data.supply.reasoning]
    #v(3pt)
    #text(size: 7.5pt, weight: "medium")[#data.supply.split_label]
  ],
)

#v(10pt)

// ---------- line items ----------
// Column count is kept to at most ten so the description column always has
// room. The CGST/SGST split is shown in the totals and the tax breakup block
// rather than as four extra per-line columns, which crushed the layout.
#let show_disc = data.table.show_discount
#let show_tax = data.tax.charged

#set text(size: 8pt)
#table(
  columns: (auto, 1fr, auto, auto, auto)
    + (if show_disc { (auto,) } else { () })
    + (auto,)
    + (if show_tax { (auto, auto) } else { () })
    + (auto,),
  align: (center + top, left + top, center + top, right + top, right + top)
    + (if show_disc { (right + top,) } else { () })
    + (right + top,)
    + (if show_tax { (right + top, right + top) } else { () })
    + (right + top,),
  stroke: none,
  inset: (x: 4pt, y: 5pt),
  fill: (_, y) => if y == 0 { rgb("#f2f4f8") },

  table.header(
    [#label("#")], [#label("Description")], [#label("HSN/SAC")],
    [#label("Qty")], [#label("Rate")],
    ..(if show_disc { ([#label("Disc")],) } else { () }),
    [#label("Taxable")],
    ..(if show_tax { ([#label(data.table.tax_rate_header)],
                      [#label(data.table.tax_header)]) } else { () }),
    [#label("Amount")],
  ),

  ..data.lines.map(l => (
    [#text(size: 8pt, fill: muted)[#l.index]],
    [#l.description],
    [#text(size: 7.5pt)[#l.hsn_sac]],
    [#money(l.quantity) #text(size: 7pt, fill: muted)[#l.unit]],
    [#money(l.rate)],
    ..(if show_disc { (money(l.discount),) } else { () }),
    [#money(l.taxable)],
    ..(if show_tax { (money(l.tax_rate), money(l.tax)) } else { () }),
    [#money(l.total)],
  )).flatten(),

  table.hline(stroke: 0.4pt + rule),
)
#set text(size: 9pt)

#v(8pt)

// ---------- totals ----------
#grid(
  columns: (1fr, auto),
  gutter: 14pt,
  [
    #label("Amount in words")
    #v(3pt)
    #text(size: 9pt, weight: "medium")[#data.totals.amount_words]

    #if data.tax.declaration != none [
      #v(8pt)
      #block(
        fill: rgb("#fff6e8"), inset: 7pt, radius: 2pt, width: 100%,
        text(size: 8pt, weight: "medium")[#data.tax.declaration],
      )
    ]

    #if data.upi != none [
      #v(8pt)
      #grid(
        columns: (auto, auto), gutter: 8pt, align: (top, horizon),
        image(data.upi.qr_path, width: 24mm),
        text(size: 7.5pt, fill: muted)[
          #label("Pay by UPI") \
          #data.upi.vpa \
          #data.upi.amount
        ],
      )
    ]
  ],
  [
    #set text(size: 9pt)
    #table(
      columns: (auto, auto),
      align: (left, right),
      stroke: none,
      inset: (x: 6pt, y: 3.5pt),
      ..data.totals.rows.map(r => (
        [#text(fill: muted)[#r.label]], [#money(r.value)],
      )).flatten(),
      table.hline(stroke: 0.4pt + rule),
      [#text(weight: "bold")[#data.totals.grand_label]],
      [#text(weight: "bold", size: 11pt)[#money(data.totals.grand_total)]],
    )
  ],
)

// ---------- tax breakup ----------
// This is where the CGST/SGST split is shown per rate, so a recipient can
// check each half against the taxable value on a phone calculator.
#if data.tax.charged [
  #v(10pt)
  #label("Tax breakup")
  #v(3pt)
  #set text(size: 8pt)
  #table(
    columns: (auto, auto, auto, auto),
    align: (left, right, right, right),
    stroke: none,
    inset: (x: 6pt, y: 3.5pt),
    fill: (_, y) => if y == 0 { rgb("#f2f4f8") },
    [#label("Rate")], [#label("Taxable value")],
    [#label(data.summary_headers.first)], [#label(data.summary_headers.second)],
    ..data.summary.map(s => (
      [#s.rate], [#money(s.taxable)], [#money(s.first)], [#money(s.second)],
    )).flatten(),
  )
  #set text(size: 9pt)
]

// ---------- terms ----------
#if data.doc.terms.len() > 0 [
  #v(10pt)
  #label("Terms")
  #v(3pt)
  #set text(size: 8pt, fill: muted)
  #for (i, t) in data.doc.terms.enumerate() [
    #box(width: 10pt)[#text(size: 7pt)[#(i + 1).]] #t \
  ]
]

#if data.doc.notes != none [
  #v(8pt)
  #label("Notes")
  #v(3pt)
  #text(size: 8pt, fill: muted)[#data.doc.notes]
]

// ---------- statutory disclaimer ----------
#v(10pt)
#block(
  fill: rgb("#f2f4f8"), inset: 8pt, radius: 2pt, width: 100%,
  text(size: 7.5pt, fill: muted)[
    *#data.doc.disclaimer* \
    #data.manifest.scope
  ],
)
