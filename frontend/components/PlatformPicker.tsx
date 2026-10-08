"use client";

import { Toggle } from "@/components/ui/toggle";
import { Button } from "@/components/ui/button";

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
          <Toggle
            key={option}
            pressed={active}
            onPressedChange={() => onChange(toggle(selected, option))}
            className="h-auto min-w-0 rounded-full border border-input px-3 py-1 text-sm font-normal data-[pressed]:border-primary data-[pressed]:bg-primary data-[pressed]:text-primary-foreground"
          >
            {option}
          </Toggle>
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
          <Button type="button" variant="link" size="sm" onClick={onToggleShowAll} className="mt-2 h-auto p-0 text-xs text-muted-foreground">
            {showAll ? "View fewer platforms" : "View more platforms"}
          </Button>
        </>
      )}
    </>
  );
}
