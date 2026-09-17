// Payment reminder template.
//
// This template receives ONLY already-computed strings, passed in as JSON via
// `--input payload`. It performs no arithmetic and no date handling -- there is
// no addition, no subtraction and no day counting anywhere below. Every number
// and every date printed is a string produced by ageing.py and cross-checked by
// redates.py before this file is ever invoked.
//
// The title comes from `doc.title`, which can only ever be "PAYMENT REMINDER"
// or "FINAL PAYMENT REMINDER" because ReminderStage has exactly three members
// and none of them is a demand under any statute. The wording of the escalation
// itself arrives in `doc.opening` and `doc.disclaimer`; nothing in this file
// adds to it. tests/test_no_legal_notice.py greps this file to keep it that way.

#let data = json(bytes(sys.inputs.payload))

#let ink = rgb("#14161d")
#let muted = rgb("#5e6575")
#let rule = rgb("#d7dbe3")
#let accent = if data.ageing.is_final { rgb("#8a2f24") } else { rgb("#1b3a6b") }

#set document(title: data.doc.title + " " + data.doc.number, author: data.supplier.name)
#set page(
  paper: "a4",
  margin: (x: 16mm, y: 13mm),
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
      #if data.supplier.state != none [#data.supplier.state]
      #if data.supplier.email != none [ \ #data.supplier.email]
      #if data.supplier.phone != none [ · #data.supplier.phone]
    ]
  ],
  [
    #text(size: 16pt, weight: "bold", fill: accent)[#data.doc.title]
    #v(4pt)
    #text(size: 8pt)[
      #label("No") #h(4pt) #data.doc.number \
      #label("Position as at") #h(4pt) #data.doc.as_of
    ]
  ],
)

#v(6pt)
#line(length: 100%, stroke: 0.8pt + accent)
#v(8pt)

// ---------- recipient and ageing ----------
#grid(
  columns: (1fr, 1fr),
  gutter: 14pt,
  [
    #label("Reminder to")
    #v(3pt)
    #text(weight: "semibold")[#data.client.name] \
    #text(size: 8pt, fill: muted)[
      #for l in data.client.address [#l \ ]
      #if data.client.gstin != none [GSTIN: #data.client.gstin \ ]
      #if data.client.state != none [#data.client.state]
      #if data.client.email != none [ \ #data.client.email]
      #if data.client.phone != none [ · #data.client.phone]
    ]
  ],
  [
    #label("Status")
    #v(3pt)
    #text(weight: "semibold", fill: accent)[#data.ageing.status]
    #h(5pt)
    #text(size: 7.5pt, fill: muted)[(#data.ageing.bucket)]
    #v(3pt)
    #text(size: 7.5pt, fill: muted)[#data.ageing.bucket_why]
    #v(3pt)
    #text(size: 7.5pt, fill: muted)[
      Due #data.ageing.due_date · #data.ageing.derivation
    ]
  ],
)

#v(7pt)
#text(size: 9pt)[#data.doc.opening]
#v(7pt)

// ---------- what is being chased ----------
#block(
  fill: rgb("#f2f4f8"), inset: 7pt, radius: 2pt, width: 100%,
  [
    #label("Against")
    #v(3pt)
    #grid(
      columns: (auto, 1fr),
      gutter: 12pt,
      align: (left + top, left + top),
      [
        #text(weight: "semibold")[#data.reference.label #data.reference.number] \
        #text(size: 8pt, fill: muted)[dated #data.reference.dated]
      ],
      [
        #text(size: 7.5pt, fill: muted)[
          #data.reference.provenance
          Amount: #data.reference.amount_source.
        ]
      ],
    )
  ],
)

#v(10pt)

// ---------- payments recorded ----------
#if data.payments.len() > 0 [
  #label("Payments recorded against this reference")
  #v(3pt)
  #set text(size: 8pt)
  #table(
    columns: (auto, auto, 1fr, auto),
    align: (left + top, left + top, left + top, right + top),
    stroke: none,
    inset: (x: 5pt, y: 3.5pt),
    fill: (_, y) => if y == 0 { rgb("#f2f4f8") },
    [#label("Received")], [#label("Method")], [#label("Reference")],
    [#label("Amount")],
    ..data.payments.map(p => (
      [#p.received_on], [#p.method], [#text(size: 7.5pt)[#p.reference]],
      [#money(p.amount)],
    )).flatten(),
    table.hline(stroke: 0.4pt + rule),
  )
  #set text(size: 9pt)
  #v(8pt)
] else [
  #text(size: 8pt, fill: muted)[No payment is recorded against this reference.]
  #v(8pt)
]

// ---------- totals ----------
// The amount in words sits on its own full-width row BELOW this grid, not
// beside the figures. In a two-column layout a words line long enough to wrap
// is extracted from the PDF interleaved with the totals column, and
// reminder_verify.py then cannot find it -- which is how it was caught.
#grid(
  columns: (1fr, auto),
  gutter: 14pt,
  [
    #if data.upi != none [
      #grid(
        columns: (auto, auto), gutter: 8pt, align: (top, horizon),
        image(data.upi.qr_path, width: 20mm),
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

#v(6pt)
#block(width: 100%)[
  #label("Amount in words")
  #v(3pt)
  #text(size: 9pt, weight: "medium")[#data.totals.amount_words]
]

// ---------- interest, when it was declared ----------
#if data.interest != none [
  #v(8pt)
  #label("Interest")
  #v(3pt)
  #block(
    fill: rgb("#fff6e8"), inset: 7pt, radius: 2pt, width: 100%,
    breakable: false,
    text(size: 8pt)[
      #data.interest.rate per annum on the balance outstanding, from the due
      date, on a #data.interest.day_count day year — as declared in
      *#data.interest.declared_in*. \
      #v(2pt)
      #text(size: 7.5pt, fill: muted)[
        #data.interest.formula · #data.interest.basis. Where part was paid late
        this understates the charge rather than overstating it.
      ]
    ],
  )
]

// ---------- how this was aged, and what went before ----------
// Kept as one compact block: it is the audit trail for the tone of the letter,
// and a reader checking it wants the boundaries and the earlier dates together.
#v(8pt)
#text(size: 7.5pt, fill: muted)[
  #label("How this was aged") \
  Ageing boundaries used: #data.ageing.boundaries.
  #data.ageing.stage_why.
  #if data.history.len() > 0 [
    Earlier reminders on this reference: #data.history.join(" · ").
  ]
]

// ---------- terms and notes ----------
#if data.doc.terms.len() > 0 [
  #v(8pt)
  #label("Terms")
  #v(3pt)
  #set text(size: 8pt, fill: muted)
  #for (i, t) in data.doc.terms.enumerate() [
    #box(width: 10pt)[#text(size: 7pt)[#(i + 1).]] #t \
  ]
  #set text(size: 9pt, fill: ink)
]

#if data.doc.notes != none [
  #v(7pt)
  #label("Notes")
  #v(3pt)
  #text(size: 8pt, fill: muted)[#data.doc.notes]
]

// ---------- disclaimer ----------
// breakable: false is load-bearing. Split across a page boundary, the footer
// manifest lands between the two halves and the disclaimer no longer reads as
// one statement -- which reminder_verify.py refuses, having found exactly that.
// It moves whole to the next page rather than being torn in two.
#v(8pt)
#block(
  fill: rgb("#f2f4f8"), inset: 8pt, radius: 2pt, width: 100%,
  breakable: false,
  par(leading: 0.48em, text(size: 7.5pt, fill: muted)[
    *#data.doc.disclaimer* \
    #data.manifest.scope
  ]),
)
