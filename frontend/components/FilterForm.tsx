"use client";

import { useEffect, useState } from "react";
import { getFacets, type HardFilters, type SoftPreferences } from "@/lib/api";
import PlatformPicker, { PillToggle, PRIMARY_PLATFORMS } from "@/components/PlatformPicker";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Slider } from "@/components/ui/slider";
import { Library } from "lucide-react";

const MIN_LENGTH_HOURS = 1;
const MAX_LENGTH_HOURS = 100;
const DEFAULT_LENGTH_HOURS = 10;

// The slider itself only ever shows 0-10 (coarser, easier to drag than 101
// discrete stops) - the backend's target_story_gameplay_ratio is still a
// 0-100 scale (matches game.story_gameplay_ratio's enrichment range, see
// services/scoring.py), so every UI value is multiplied by 10 on the way
// out and divided by 10 when a saved default comes back in.
const MAX_STORY_GAMEPLAY_UI = 10;
const DEFAULT_STORY_GAMEPLAY_UI = 5;

// Niche genres collapsed behind "View more genres" by default, same pattern
// as PlatformPicker's primary/secondary split - unlike platforms (a fixed,
// known set where PRIMARY_PLATFORMS lists what stays visible), genres come
// from the live catalog (GET /games/facets), so this is a short deny-list
// of the ones to hide rather than an allow-list of everything else.
const SECONDARY_GENRES = ["Music", "Pinball", "Racing", "Simulator", "Sport", "Roguelite"];

interface Props {
  onSubmit: (hardFilters: HardFilters, softPreferences: SoftPreferences) => void;
  loading: boolean;
  // Phase 5: a signed-in user's saved defaults, loaded async by the parent
  // page from GET /profile/preferences - undefined while that load is in
  // flight (or the user is signed out), so the form keeps its own blank
  // defaults rather than flashing saved values in after the fact.
  initialHardFilters?: HardFilters;
  initialSoftPreferences?: SoftPreferences;
  onSaveDefaults?: (hardFilters: HardFilters, softPreferences: SoftPreferences) => void;
  saveDefaultsState?: "idle" | "saving" | "saved" | "error";
}

export default function FilterForm({
  onSubmit,
  loading,
  initialHardFilters,
  initialSoftPreferences,
  onSaveDefaults,
  saveDefaultsState = "idle",
}: Props) {
  const [platformOptions, setPlatformOptions] = useState<string[]>([]);
  const [genreOptions, setGenreOptions] = useState<string[]>([]);
  const [facetsError, setFacetsError] = useState<string | null>(null);
  const [showAllPlatforms, setShowAllPlatforms] = useState(false);
  const [showAllGenres, setShowAllGenres] = useState(false);

  const [platforms, setPlatforms] = useState<string[]>([]);
  const [genres, setGenres] = useState<string[]>([]);
  const [requireMultiplayer, setRequireMultiplayer] = useState(false);
  const [lengthEnabled, setLengthEnabled] = useState(false);
  const [targetLengthHours, setTargetLengthHours] = useState<number>(DEFAULT_LENGTH_HOURS);
  const [storyGameplayEnabled, setStoryGameplayEnabled] = useState(false);
  const [storyGameplayUi, setStoryGameplayUi] = useState<number>(DEFAULT_STORY_GAMEPLAY_UI);

  // Tracks edits made after the last "Saved as default" - without this, the
  // button would keep reading "Saved as default" even once it no longer
  // reflects what's in the form. Reset on every new saveDefaultsState from
  // the parent (a fresh save cycle), set on any field change in between.
  const [dirtySinceSave, setDirtySinceSave] = useState(false);
  useEffect(() => {
    setDirtySinceSave(false);
  }, [saveDefaultsState]);

  useEffect(() => {
    getFacets()
      .then((facets) => {
        setPlatformOptions(facets.platforms);
        setGenreOptions(facets.genres);
      })
      .catch((err) => setFacetsError(err instanceof Error ? err.message : "Failed to load filter options"));
  }, []);

  // Pre-fill once saved defaults arrive from the parent - keyed so this only
  // fires the first time they show up, not on every parent re-render (which
  // would otherwise stomp on whatever the user has since typed/toggled).
  useEffect(() => {
    if (!initialHardFilters || !initialSoftPreferences) return;
    setGenres(initialHardFilters.include_genres);
    setPlatforms(initialHardFilters.platforms);
    // If a saved default selected a niche platform, expand the "View more"
    // section so that selection is actually visible rather than silently
    // applied but hidden.
    if (initialHardFilters.platforms.some((p) => !PRIMARY_PLATFORMS.includes(p))) {
      setShowAllPlatforms(true);
    }
    // Same reasoning as the platform expansion above, for genres.
    if (initialHardFilters.include_genres.some((g) => SECONDARY_GENRES.includes(g))) {
      setShowAllGenres(true);
    }
    setRequireMultiplayer(initialHardFilters.require_multiplayer);
    if (initialSoftPreferences.target_length_hours != null) {
      setLengthEnabled(true);
      setTargetLengthHours(
        Math.min(MAX_LENGTH_HOURS, Math.max(MIN_LENGTH_HOURS, initialSoftPreferences.target_length_hours))
      );
    }
    if (initialSoftPreferences.target_story_gameplay_ratio != null) {
      setStoryGameplayEnabled(true);
      setStoryGameplayUi(Math.round(initialSoftPreferences.target_story_gameplay_ratio / 10));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialHardFilters, initialSoftPreferences]);

  function currentValues(): [HardFilters, SoftPreferences] {
    return [
      { include_genres: genres, exclude_genres: [], platforms, require_multiplayer: requireMultiplayer },
      {
        target_length_hours: lengthEnabled ? targetLengthHours : null,
        target_story_gameplay_ratio: storyGameplayEnabled ? storyGameplayUi * 10 : null,
        similar_to_game_id: null,
      },
    ];
  }

  function handleSaveDefaults() {
    if (!onSaveDefaults) return;
    const [hardFilters, softPreferences] = currentValues();
    onSaveDefaults(hardFilters, softPreferences);
  }

  const displaySaveState = dirtySinceSave && saveDefaultsState === "saved" ? "idle" : saveDefaultsState;

  const primaryGenres = genreOptions.filter((g) => !SECONDARY_GENRES.includes(g));
  const secondaryGenres = genreOptions.filter((g) => SECONDARY_GENRES.includes(g));

  function handleGenreChange(next: string[]) {
    setGenres(next);
    setDirtySinceSave(true);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const [hardFilters, softPreferences] = currentValues();
    onSubmit(hardFilters, softPreferences);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Library className="size-5 text-primary" aria-hidden="true" />
          Find your next game
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="lengthEnabled"
                    checked={lengthEnabled}
                    onCheckedChange={(checked) => {
                      setLengthEnabled(checked);
                      setDirtySinceSave(true);
                    }}
                  />
                  <Label htmlFor="lengthEnabled">Target length</Label>
                </div>
                {lengthEnabled && (
                  <span className="text-sm text-muted-foreground">
                    {targetLengthHours >= MAX_LENGTH_HOURS
                      ? `${MAX_LENGTH_HOURS}+ hours`
                      : `${targetLengthHours} hours`}
                  </span>
                )}
              </div>
              <Slider
                id="targetLengthHours"
                disabled={!lengthEnabled}
                min={MIN_LENGTH_HOURS}
                max={MAX_LENGTH_HOURS}
                step={1}
                value={targetLengthHours}
                onValueChange={(value) => {
                  setTargetLengthHours(Array.isArray(value) ? value[0] : value);
                  setDirtySinceSave(true);
                }}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="storyGameplayEnabled"
                    checked={storyGameplayEnabled}
                    onCheckedChange={(checked) => {
                      setStoryGameplayEnabled(checked);
                      setDirtySinceSave(true);
                    }}
                  />
                  <Label htmlFor="storyGameplayEnabled">Story vs. gameplay focus</Label>
                </div>
                {storyGameplayEnabled && (
                  <span className="text-sm text-muted-foreground">
                    {storyGameplayUi}/{MAX_STORY_GAMEPLAY_UI}
                  </span>
                )}
              </div>
              <Slider
                id="targetStoryGameplayRatio"
                disabled={!storyGameplayEnabled}
                min={0}
                max={MAX_STORY_GAMEPLAY_UI}
                step={1}
                value={storyGameplayUi}
                onValueChange={(value) => {
                  setStoryGameplayUi(Array.isArray(value) ? value[0] : value);
                  setDirtySinceSave(true);
                }}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Story focus: 0 = pure gameplay, {MAX_STORY_GAMEPLAY_UI} = pure narrative. AI-estimated per game.
          </p>

          {/* No popularity slider - the engine now applies a small, always-on
              discovery bias toward less-obvious games automatically, rather
              than letting the user dial popularity up or down. */}

          {facetsError && (
            <Alert variant="destructive">
              <AlertDescription>{facetsError}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-1.5">
            <Label>Platform</Label>
            <p className="text-xs text-muted-foreground">Leave empty to include all platforms.</p>
            <div className="rounded-lg border p-3">
              {platformOptions.length > 0 ? (
                <PlatformPicker
                  options={platformOptions}
                  selected={platforms}
                  onChange={(next) => {
                    setPlatforms(next);
                    setDirtySinceSave(true);
                  }}
                  showAll={showAllPlatforms}
                  onToggleShowAll={() => setShowAllPlatforms((prev) => !prev)}
                />
              ) : (
                <p className="text-sm text-muted-foreground">Loading platforms...</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Genre</Label>
            <p className="text-xs text-muted-foreground">Leave empty to include all genres.</p>
            <div className="max-h-64 overflow-y-auto rounded-lg border p-3">
              {genreOptions.length > 0 ? (
                <>
                  <PillToggle options={primaryGenres} selected={genres} onChange={handleGenreChange} />
                  {secondaryGenres.length > 0 && (
                    <>
                      {showAllGenres && (
                        <div className="mt-2">
                          <PillToggle options={secondaryGenres} selected={genres} onChange={handleGenreChange} />
                        </div>
                      )}
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        onClick={() => setShowAllGenres((prev) => !prev)}
                        className="mt-2 h-auto p-0 text-xs text-muted-foreground"
                      >
                        {showAllGenres ? "View fewer genres" : "View more genres"}
                      </Button>
                    </>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Loading genres...</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="requireMultiplayer"
              checked={requireMultiplayer}
              onCheckedChange={(checked) => {
                setRequireMultiplayer(checked);
                setDirtySinceSave(true);
              }}
            />
            <Label htmlFor="requireMultiplayer">Require multiplayer</Label>
          </div>

          <div className="flex items-center gap-4">
            <Button type="submit" disabled={loading}>
              {loading ? "Finding games..." : "Get recommendations"}
            </Button>

            {onSaveDefaults && (
              <Button
                type="button"
                variant="link"
                onClick={handleSaveDefaults}
                disabled={displaySaveState === "saving"}
                className="h-auto p-0 text-muted-foreground"
              >
                {displaySaveState === "saved"
                  ? "Saved as default"
                  : displaySaveState === "saving"
                    ? "Saving..."
                    : displaySaveState === "error"
                      ? "Couldn't save - try again"
                      : "Save as my default filters"}
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
