import React from "react";
import "./primitives.css";

export interface DataListItem {
  id: string;
  primary:    string;
  secondary?: string;
  trailing?:  React.ReactNode;
}

export interface DataListProps {
  items:       DataListItem[];
  selectedId?: string | null;
  onSelect?:   (id: string) => void;
}

export const DataList: React.FC<DataListProps> = ({ items, selectedId, onSelect }) => (
  <ul className="data-list">
    {items.map((item) => {
      const selected = selectedId === item.id;
      return (
        <li key={item.id} className="data-list__li">
          <button
            type="button"
            className={`data-list__row ${selected ? "data-list__row--selected" : ""}`}
            onClick={() => onSelect?.(item.id)}
            disabled={!onSelect}
          >
            <span className="data-list__primary">{item.primary}</span>
            {item.secondary && <span className="data-list__secondary">{item.secondary}</span>}
            {item.trailing  !== undefined && <span className="data-list__trailing">{item.trailing}</span>}
          </button>
        </li>
      );
    })}
  </ul>
);
