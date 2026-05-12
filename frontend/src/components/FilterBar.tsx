import React from "react";
import { useFilters } from "../context/FilterContext";
import { useAgencies } from "../context/AgenciesContext";
import { agencyColor } from "../lib/agencies";
import "./FilterBar.css";

export const FilterBar: React.FC = () => {
  const { filters, setDateRange, setAgencies, setSearch } = useFilters();
  const { agencies, loading: agenciesLoading } = useAgencies();

  const toggleAgency = (id: string) => {
    const next = filters.agencies.includes(id)
      ? filters.agencies.filter(a => a !== id)
      : [...filters.agencies, id];
    setAgencies(next);
  };

  return (
    <div className="filter-bar shell-filterbar">
      <div className="filter-bar__group">
        <label className="filter-bar__label">
          <span>From</span>
          <input
            type="date"
            value={filters.startDate}
            onChange={(e) => setDateRange(e.target.value, filters.endDate)}
          />
        </label>
        <label className="filter-bar__label">
          <span>To</span>
          <input
            type="date"
            value={filters.endDate}
            onChange={(e) => setDateRange(filters.startDate, e.target.value)}
          />
        </label>
      </div>

      <div className="filter-bar__pills">
        {agenciesLoading && agencies.length === 0 ? (
          <span className="filter-bar__pill-placeholder">Loading agencies…</span>
        ) : (
          agencies.map(a => {
            const active = filters.agencies.includes(a.agency_id);
            const color  = agencyColor(a.agency_id);
            return (
              <button
                key={a.agency_id}
                type="button"
                className={`agency-pill ${active ? "agency-pill--active" : ""}`}
                style={active ? { borderColor: color, color } : undefined}
                onClick={() => toggleAgency(a.agency_id)}
                title={a.agency_name}
              >
                {a.agency_id}
              </button>
            );
          })
        )}
      </div>

      <input
        type="search"
        className="filter-bar__search"
        placeholder="Search route…"
        value={filters.search}
        onChange={(e) => setSearch(e.target.value)}
      />
    </div>
  );
};
