import React from "react";
import { useFilters } from "../context/FilterContext";
import { AgencyCombobox } from "./AgencyCombobox";
import "./FilterBar.css";

export const FilterBar: React.FC = () => {
  const { filters, setDateRange, setSearch } = useFilters();

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

      <AgencyCombobox />

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
