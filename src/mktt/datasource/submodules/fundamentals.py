"""Fundamentals DataSource submodule (spec §4.4, §5.3).

Serves the `Fundamentals` form — per-symbol fields read from `MKFund.fundamentals_current`,
plus the forward-estimate curves from `MKFund.estimates_forward` on request. This is the
read side of Slice #4 (the loader is the write side); both target the same `MKFund` schema.

Design (spec §8):
- **Dependency injection**: takes a `conn_factory` (zero-arg → fresh psycopg2 connection),
  schema-parameterized. Tests inject a factory pointed at a disposable schema.
- The `(fundamentals, *)` registry row routes every id here (asset-class blind — every
  symbol has fundamentals in the same table).

`Fundamentals` form (spec §3): a `symbol × attributes` table (pandas DataFrame indexed by
symbol). `fields=None` returns all `fundamentals_current` columns; a field list narrows the
projection. `estimates=True` attaches the forward FY1/FY2 curve as extra `fy{n}_{col}` columns.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional, Sequence

import pandas as pd

from ..loaders.mkfund_loader import (
    FUNDAMENTALS_CURRENT_COLS,
    ESTIMATES_FORWARD_COLS,
)

logger = logging.getLogger("mktt.datasource.fundamentals")
if os.environ.get("MKTT_LOG_LEVEL", "").upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)

DEFAULT_SCHEMA = "MKFund"

ConnFactory = Callable[[], "object"]


def _normalize_ids(ids) -> list:
    if isinstance(ids, str):
        return [ids]
    return list(ids)


class FundamentalsSubmodule:
    """Reads `MKFund.fundamentals_current` (+ estimates) into the `Fundamentals` form.

    Parameters
    ----------
    conn_factory:
        Zero-arg callable returning a fresh DB connection (DI seam).
    schema:
        Schema holding the MKFund tables (default `MKFund`; tests pass a disposable one).
    """

    def __init__(
        self,
        conn_factory: ConnFactory,
        schema: str = DEFAULT_SCHEMA,
    ) -> None:
        self._conn_factory = conn_factory
        self.schema = schema

    # ------------------------------------------------------------------ #
    def fundamentals(
        self,
        ids,
        fields: Optional[Sequence[str]] = None,
        estimates: bool = False,
    ) -> pd.DataFrame:
        """ids → `symbol × attributes` Fundamentals frame.

        - `fields=None` → all `fundamentals_current` columns; else the projection
          (always including `symbol`). Unknown field names are ignored.
        - `estimates=True` → attach FY1/FY2 forward curve as `fy{n}_{col}` columns.
        - Missing ids are tolerated (absent from the result, no error).
        """
        ids = _normalize_ids(ids)
        if not ids:
            return self._empty(fields)

        if fields is None:
            cols = list(FUNDAMENTALS_CURRENT_COLS)
        else:
            requested = {f for f in fields}
            cols = [c for c in FUNDAMENTALS_CURRENT_COLS if c in requested or c == "symbol"]
            if "symbol" not in cols:
                cols = ["symbol"] + cols

        col_list = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(ids))
        sql = (
            f"SELECT {col_list} FROM \"{self.schema}\".fundamentals_current "
            f"WHERE symbol IN ({placeholders})"
        )
        logger.debug("fundamentals ids=%d fields=%s estimates=%s", len(ids), fields, estimates)

        rows = self._query(sql, tuple(ids))
        frame = pd.DataFrame(rows, columns=cols)
        if not frame.empty:
            frame = frame.set_index("symbol").sort_index()
        else:
            frame = pd.DataFrame(columns=[c for c in cols if c != "symbol"])
            frame.index.name = "symbol"

        if estimates:
            frame = self._attach_estimates(frame, ids)
        return frame

    # ------------------------------------------------------------------ #
    def _attach_estimates(self, frame: pd.DataFrame, ids) -> pd.DataFrame:
        est_cols = list(ESTIMATES_FORWARD_COLS)  # includes symbol (pivot key)
        col_list = ", ".join(est_cols)
        placeholders = ", ".join(["%s"] * len(ids))
        sql = (
            f"SELECT {col_list} FROM \"{self.schema}\".estimates_forward "
            f"WHERE symbol IN ({placeholders})"
        )
        rows = self._query(sql, tuple(ids))
        est = pd.DataFrame(rows, columns=est_cols)
        if est.empty:
            return frame
        # pivot fy1/fy2 into fy{n}_{col} wide columns keyed by symbol
        value_cols = [c for c in est_cols if c not in ("symbol", "fy_period")]
        wide_parts = {}
        for fy in sorted(est["fy_period"].dropna().unique()):
            sub = est[est["fy_period"] == fy].set_index("symbol")[value_cols]
            sub.columns = [f"fy{int(fy)}_{c}" for c in value_cols]
            wide_parts[fy] = sub
        if not wide_parts:
            return frame
        wide = pd.concat(wide_parts.values(), axis=1)
        return frame.join(wide, how="left")

    # ------------------------------------------------------------------ #
    def _empty(self, fields) -> pd.DataFrame:
        cols = (
            [c for c in FUNDAMENTALS_CURRENT_COLS if c != "symbol"]
            if fields is None
            else [f for f in fields if f != "symbol"]
        )
        df = pd.DataFrame(columns=cols)
        df.index.name = "symbol"
        return df

    def _query(self, sql: str, params):
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
