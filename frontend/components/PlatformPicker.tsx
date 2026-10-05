"use client";

// Shown by default - current-gen consoles + Switch + the PC ecosystem,
// what most players are actually asking about. Exact strings must match
// IGDB's platform names (see GET /games/facets) - "PC (Microsoft
// Windows)", not "PC". Everything else (older consoles, handhelds, VR
// headsets, ...) is real but far more niche, and sits behind "View more
// platforms" instead of cluttering the default view. Exported so a parent
// can decide whether to auto-expand (e.g. a saved selection includes a
// niche platform) - this component doesn't do that itself, since tying
// auto-expand to `selected` here would re-expand the moment a parent
// re-renders with that same selection, fighting a user who just collapsed
// it on purpose.
export const PRIMARY_PLATFORMS = [
  "PC (Microsoft Windows)",
  "Mac",
  "Linux",
  "PlayStation 5",
  "PlayStation 4",
  "Xbox Series X|S",
  "Xbox One",
  "Nintendo Switch",
];

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function PillToggle({
  options,
  selected,
  onChange,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = selected.includes(option);
        return (
          <button
            key={option}
            type="button"
            onClick={() => onChange(toggle(selected, option))}
            className={`rounded-full border px-3 py-1 text-sm ${
              active ? "border-gray-900 bg-gray-900 text-white" : "border-gray-300 bg-white text-gray-700"
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

export default function PlatformPicker({
  options,
  selected,
  onChange,
  showAll,
  onToggleShowAll,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  showAll: boolean;
  onToggleShowAll: () => void;
}) {
  const primary = PRIMARY_PLATFORMS.filter((p) => options.includes(p));
  const secondary = options.filter((p) => !PRIMARY_PLATFORMS.includes(p));

  return (
    <>
      <PillToggle options={primary} selected={selected} onChange={onChange} />
      {secondary.length > 0 && (
        <>
          {showAll && (
            <div className="mt-2">
              <PillToggle options={secondary} selected={selected} onChange={onChange} />
            </div>
          )}
          <button
            type="button"
            onClick={onToggleShowAll}
            className="mt-2 text-xs text-gray-500 underline hover:text-gray-900"
          >
            {showAll ? "View fewer platforms" : "View more platforms"}
          </button>
        </>
      )}
    </>
  );
}
