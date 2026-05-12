import React from "react";
import { useFilters } from "../context/FilterContext";
import { AGENCY_LIST, agencyName } from "../lib/agencies";
import "./FilterBar.css";

export const FilterBar: React.FC = () => {
  const { filters, setDateRange, setAgencies, setSearch } = useFilters();

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
        {AGENCY_LIST.map(a => {
          const active = filters.agencies.includes(a.id);
          return (
            <button
              key={a.id}
              type="button"
              className={`agency-pill ${active ? "agency-pill--active" : ""}`}
              style={active ? { borderColor: a.color, color: a.color } : undefined}
              onClick={() => toggleAgency(a.id)}
              title={agencyName(a.id)}
            >
              {a.id}
            </button>
          );
        })}
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
