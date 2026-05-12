import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAgencies } from "../context/AgenciesContext";
import { useFilters } from "../context/FilterContext";
import { agencyColor } from "../lib/agencies";
import "./AgencyCombobox.css";

const MAX_CHIPS = 3;

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

  const selected = filters.agencies;          // [] = "all"
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return agencies
      .filter(a => showInactive || a.has_data !== false)
      .filter(a => !term
        || a.agency_id.toLowerCase().includes(term)
        || a.agency_name.toLowerCase().includes(term))
      .sort((x, y) => x.agency_name.localeCompare(y.agency_name));
  }, [agencies, search, showInactive]);

  const toggle = useCallback((id: string) => {
    setAgencies(selectedSet.has(id) ? selected.filter(s => s !== id) : [...selected, id]);
  }, [selected, selectedSet, setAgencies]);

  const removeChip = (id: string) => setAgencies(selected.filter(s => s !== id));
  const clearAll      = () => setAgencies([]);
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
            {loading && visible.length === 0 && (
              <li className="agency-combobox__empty">Loading…</li>
            )}
            {!loading && visible.length === 0 && (
              <li className="agency-combobox__empty">No matches.</li>
            )}
            {visible.map(a => {
              const active = selectedSet.has(a.agency_id);
              return (
                <li key={a.agency_id} className="agency-combobox__row">
                  <label className="agency-combobox__row-label">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => toggle(a.agency_id)}
                    />
                    <span
                      className="agency-combobox__row-code"
                      style={{ color: agencyColor(a.agency_id) }}
                    >{a.agency_id}</span>
                    <span className="agency-combobox__row-name">{a.agency_name}</span>
                    {a.monitored && <span className="agency-combobox__rt">RT</span>}
                    {a.has_data === false && <span className="agency-combobox__inactive">inactive</span>}
                  </label>
                </li>
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
              <span>Show 511 internal &amp; inactive</span>
            </label>
          </div>
        </div>
      )}
    </div>
  );
};
