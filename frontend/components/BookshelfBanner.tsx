// Decorative banner for the home page - a cozy, flat-illustration bookshelf
// scene. Hand-built inline SVG (no image asset/generation tool available),
// reusing the theme's --spine-1..5 colors (see globals.css) so it stays in
// sync with the same palette the results list's book-spine accents use,
// rather than hardcoding a second, disconnected set of colors.
//
// Book layout is a fixed array, not randomized - randomizing per-render
// would mismatch between server and client output and break hydration.

interface Book {
  w: number;
  h: number;
  color: string;
  rotate: number;
  band?: boolean;
}

const BOOKS: Book[] = [
  { w: 24, h: 120, color: "var(--spine-1)", rotate: -2 },
  { w: 30, h: 140, color: "var(--spine-3)", rotate: 1, band: true },
  { w: 20, h: 100, color: "var(--spine-4)", rotate: 0 },
  { w: 28, h: 150, color: "var(--spine-2)", rotate: -1, band: true },
  { w: 22, h: 110, color: "var(--spine-5)", rotate: 2 },
  { w: 34, h: 130, color: "var(--spine-1)", rotate: 0, band: true },
  { w: 18, h: 95, color: "var(--secondary)", rotate: -3 },
  { w: 26, h: 135, color: "var(--spine-3)", rotate: 1 },
  { w: 24, h: 115, color: "var(--spine-4)", rotate: 0, band: true },
  { w: 30, h: 145, color: "var(--spine-2)", rotate: -2 },
  { w: 20, h: 105, color: "var(--spine-5)", rotate: 2 },
  { w: 26, h: 125, color: "var(--spine-1)", rotate: 0, band: true },
  { w: 22, h: 100, color: "var(--spine-3)", rotate: -1 },
  { w: 28, h: 140, color: "var(--spine-4)", rotate: 1 },
];

const SHELF_Y = 172;
const GAP = 4;
const START_X = 44;

function layoutBooks(books: Book[]) {
  let x = START_X;
  return books.map((book) => {
    const placed = { ...book, x };
    x += book.w + GAP;
    return placed;
  });
}

export default function BookshelfBanner() {
  const placed = layoutBooks(BOOKS);

  return (
    <div className="overflow-hidden rounded-xl border bg-muted">
      <svg
        viewBox="0 0 800 200"
        className="h-auto w-full"
        role="img"
        aria-label="An illustration of a cozy bookshelf"
      >
        {/* Warm lamplight glow, upper right */}
        <defs>
          <radialGradient id="lampGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="660" cy="55" r="110" fill="url(#lampGlow)" />

        {/* Books, standing on the shelf */}
        {placed.map((book, i) => (
          <g key={i} transform={`rotate(${book.rotate} ${book.x + book.w / 2} ${SHELF_Y})`}>
            <rect
              x={book.x}
              y={SHELF_Y - book.h}
              width={book.w}
              height={book.h}
              rx="2"
              fill={book.color}
            />
            {book.band && (
              <rect
                x={book.x + 3}
                y={SHELF_Y - book.h + 14}
                width={book.w - 6}
                height="3"
                rx="1.5"
                fill="var(--card)"
                opacity="0.55"
              />
            )}
          </g>
        ))}

        {/* Potted plant, to the right of the books */}
        <g>
          <path d="M 560 172 L 596 172 L 590 148 L 566 148 Z" fill="var(--secondary)" />
          <path
            d="M 578 148 C 570 120 548 112 538 96 C 556 100 572 112 578 134 C 584 108 602 96 616 92 C 608 110 590 122 582 148 Z"
            fill="var(--spine-2)"
          />
        </g>

        {/* Shelf plank */}
        <rect x="0" y={SHELF_Y} width="800" height="10" fill="var(--secondary)" />
        <rect x="0" y={SHELF_Y + 10} width="800" height="6" fill="var(--border)" />
      </svg>
    </div>
  );
}
