import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAgencies } from "../context/AgenciesContext";
import { useFilters } from "../context/FilterContext";
import { agencyColor, type AgencyMeta } from "../lib/agencies";
import "./AgencyCombobox.css";

const MAX_CHIPS = 6;

/** Canonical order across all modes the 511.org operators feed produces.
 *  Anything not in this list lands in MODE_FALLBACK. */
const MODE_ORDER: ReadonlyArray<string> = ["bus", "rail", "ferry", "multi", "other"];
const MODE_LABELS: Record<string, string> = {
  bus:   "Bus",
  rail:  "Rail",
  ferry: "Ferry",
  multi: "Multi-modal",
  other: "Other",
};
const MODE_FALLBACK = "other";

function modeOf(a: AgencyMeta): string {
  const t = (a.agency_type ?? "").toLowerCase();
  return MODE_ORDER.includes(t) ? t : MODE_FALLBACK;
}

function renderRow(
  a: AgencyMeta,
  active: boolean,
  toggle: (id: string) => void,
): React.ReactNode {
  return (
    <li key={a.agency_id} className="agency-combobox__row">
      <label className="agency-combobox__row-label">
        <input type="checkbox" checked={active} onChange={() => toggle(a.agency_id)} />
        <span className="agency-combobox__row-code" style={{ color: agencyColor(a.agency_id) }}>
          {a.agency_id}
        </span>
        <span className="agency-combobox__row-name">{a.agency_name}</span>
        {a.monitored && <span className="agency-combobox__rt">RT</span>}
        {a.has_data === false && <span className="agency-combobox__inactive">inactive</span>}
      </label>
    </li>
  );
}

export const AgencyCombobox: React.FC = () => {
  const { agencies, loading } = useAgencies();
  const { filters, setAgencies } = useFilters();
  const [open, setOpen]                 = useState(false);
  const [search, setSearch]             = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on click-outside.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const selected    = filters.agencies;          // [] = "all"
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const groups = useMemo(() => {
    const term = search.trim().toLowerCase();
    const filtered = agencies
      .filter(a => showInactive || a.has_data !== false)
      .filter(a => !term
        || a.agency_id.toLowerCase().includes(term)
        || a.agency_name.toLowerCase().includes(term));

    const byMode = new Map<string, AgencyMeta[]>();
    for (const a of filtered) {
      const m = modeOf(a);
      const bucket = byMode.get(m) ?? [];
      bucket.push(a);
      byMode.set(m, bucket);
    }
    // Within each mode: monitored first, then alpha by name.
    for (const list of byMode.values()) {
      list.sort((x, y) => {
        const mx = x.monitored ? 0 : 1;
        const my = y.monitored ? 0 : 1;
        if (mx !== my) return mx - my;
        return x.agency_name.localeCompare(y.agency_name);
      });
    }
    return MODE_ORDER
      .map(mode => ({ mode, rows: byMode.get(mode) ?? [] }))
      .filter(g => g.rows.length > 0);
  }, [agencies, search, showInactive]);
  const totalVisible = groups.reduce((s, g) => s + g.rows.length, 0);

  const toggle = useCallback((id: string) => {
    setAgencies(selectedSet.has(id) ? selected.filter(s => s !== id) : [...selected, id]);
  }, [selected, selectedSet, setAgencies]);

  /** Toggle every agency in a mode group on or off.  If all are already
   *  selected, deselect them; otherwise add the missing ones.  The
   *  resulting agency_id array flows through FilterContext, which
   *  drives every section's per-agency endpoint filter. */
  const toggleGroup = (rows: AgencyMeta[]) => {
    const ids = rows.map(r => r.agency_id);
    const allOn = ids.every(id => selectedSet.has(id));
    if (allOn) {
      setAgencies(selected.filter(s => !ids.includes(s)));
    } else {
      const next = new Set(selected);
      for (const id of ids) next.add(id);
      setAgencies([...next]);
    }
  };

  const removeChip      = (id: string) => setAgencies(selected.filter(s => s !== id));
  const clearAll        = () => setAgencies([]);
  const selectMonitored = () => setAgencies(
    agencies.filter(a => a.monitored && a.has_data !== false).map(a => a.agency_id),
  );

  const chipIds  = selected.slice(0, MAX_CHIPS);
  const overflow = selected.length - chipIds.length;
  const triggerLabel = selected.length === 0 ? "All agencies" : null;

  return (
    <div className="agency-combobox" ref={rootRef}>
      <button
        type="button"
        className="agency-combobox__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
      >
        <span className="agency-combobox__trigger-label">Agencies:</span>
        {triggerLabel && <span className="agency-combobox__trigger-all">{triggerLabel}</span>}
        {chipIds.map(id => (
          <span
            key={id}
            className="agency-combobox__chip"
            style={{ borderColor: agencyColor(id), color: agencyColor(id) }}
          >
            {id}
            <span
              className="agency-combobox__chip-x"
              role="button"
              aria-label={`Remove ${id}`}
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); removeChip(id); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); removeChip(id); } }}
            >✕</span>
          </span>
        ))}
        {overflow > 0 && <span className="agency-combobox__overflow">+{overflow}</span>}
        <span className="agency-combobox__caret">▾</span>
      </button>

      {open && (
        <div className="agency-combobox__panel" role="listbox" aria-multiselectable="true">
          <input
            type="search"
            className="agency-combobox__search"
            placeholder="Search agencies…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />

          <ul className="agency-combobox__list">
            {loading && totalVisible === 0 && (
              <li className="agency-combobox__empty">Loading…</li>
            )}
            {!loading && totalVisible === 0 && (
              <li className="agency-combobox__empty">No matches.</li>
            )}
            {groups.map(({ mode, rows }) => {
              const ids = rows.map(r => r.agency_id);
              const allOn = ids.every(id => selectedSet.has(id));
              const anyOn = ids.some(id => selectedSet.has(id));
              return (
                <React.Fragment key={mode}>
                  <li className="agency-combobox__group-header">
                    <button
                      type="button"
                      className="agency-combobox__group-toggle"
                      aria-pressed={allOn}
                      onClick={() => toggleGroup(rows)}
                      aria-label={allOn ? `Deselect all ${MODE_LABELS[mode]}` : `Select all ${MODE_LABELS[mode]}`}
                    >
                      <span
                        className={`agency-combobox__group-checkbox ${
                          allOn ? "agency-combobox__group-checkbox--on"
                          : anyOn ? "agency-combobox__group-checkbox--some" : ""
                        }`}
                        aria-hidden="true"
                      />
                      <span>{MODE_LABELS[mode]}</span>
                    </button>
                    <span className="agency-combobox__group-count">{rows.length}</span>
                  </li>
                  {rows.map(a => renderRow(a, selectedSet.has(a.agency_id), toggle))}
                </React.Fragment>
              );
            })}
          </ul>

          <div className="agency-combobox__footer">
            <button type="button" className="agency-combobox__action" onClick={selectMonitored}>
              Monitored only
            </button>
            <button type="button" className="agency-combobox__action" onClick={clearAll}>
              Clear
            </button>
            <label className="agency-combobox__toggle">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
              />
              <span>Show all agencies</span>
            </label>
          </div>
        </div>
      )}
    </div>
  );
};
