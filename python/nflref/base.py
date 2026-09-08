"""The dataset contract every nflverse-derived source implements."""
from __future__ import annotations

import abc

import pandas as pd


class NflDataset(abc.ABC):
    """One nflverse data release, fetched season by season.

    Contract for a new dataset:
      * `name`     -- short lowercase id ("player_stats", "schedules"). Also
                      the snapshot subdir under season/nflverse/<name>/.
      * `label`    -- human label for a UI / log line.
      * `EARLIEST` -- oldest season nflverse publishes this dataset for (module
                      or class attribute). Older asks return an empty frame.
      * `_asset(season)` -- the release asset path on nflverse-data, e.g.
                      `player_stats/player_stats_2024.parquet`. `api.
                      read_release_parquet` turns that into the download URL.
      * `_tidy(df)` -- optional: trim / rename the raw release frame to just
                      the columns this codebase needs. Default: passthrough.
      * `fetch(season, reload=False)` -- snapshot-first (via `nflref.cache`),
                      live only when the snapshot is missing or `reload`. MUST
                      degrade to an empty frame rather than raise when the
                      upstream is unavailable; never requires credentials.

    Everything shared -- the snapshot round-trip, the EARLIEST guard, the
    empty-frame degrade -- lives in `fetch()` here; a subclass supplies only
    `_asset` and (optionally) `_tidy`.
    """

    name: str = ""
    label: str = ""
    #: oldest season this dataset exists for; a class attr overrides a
    #: module-level EARLIEST (used when one module backs several datasets).
    EARLIEST: int | None = None

    @abc.abstractmethod
    def _asset(self, season: str) -> str:
        """Release asset path, e.g. 'player_stats/player_stats_2024.parquet'."""
        raise NotImplementedError

    def _tidy(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def _earliest(self) -> int | None:
        if self.EARLIEST is not None:
            return self.EARLIEST
        try:
            mod = __import__(f"nflref.{self.name}", fromlist=["EARLIEST"])
            return getattr(mod, "EARLIEST", None)
        except Exception:
            return None

    def fetch(self, season: str, reload: bool = False) -> pd.DataFrame:
        """This dataset's rows for the season as a tidy DataFrame.

        Snapshot-first; `reload` forces a live re-fetch that rewrites the
        snapshot. Returns an empty DataFrame when nothing resolves (before
        EARLIEST, no network + no snapshot, a malformed asset).
        """
        from . import api, cache

        season = str(season)
        earliest = self._earliest()
        try:
            if earliest is not None and int(season) < earliest:
                return pd.DataFrame()
        except (TypeError, ValueError):
            pass

        if not reload:
            df = cache.load(self.name, season)
            if df is not None:
                return df

        raw = None
        try:
            raw = api.read_release_parquet(self._asset(season))
        except Exception:
            raw = None

        if raw is None or raw.empty:
            if reload:                        # skipped the snapshot above
                df = cache.load(self.name, season)
                if df is not None:
                    return df
            return pd.DataFrame()

        tidy = self._tidy(raw)
        cache.save(self.name, season, tidy)
        return tidy


#: The dataset registry. TO ADD ONE: write a module with an `NflDataset`
#: subclass (a `name`, `label`, an `EARLIEST`, an `_asset`, optionally a
#: `_tidy`) and add it here. `nflref.load()` dispatches on `name`.
def _registry() -> dict[str, NflDataset]:
    from .player_stats import PlayerStats
    from .schedules import Schedules
    return {d.name: d for d in (PlayerStats(), Schedules())}


DATASETS = _registry()
