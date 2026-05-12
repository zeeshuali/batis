import React from "react";
import { downloadCsv, toCsv } from "../../lib/download";
import "./primitives.css";

export interface ExportButtonProps {
  filename: string;
  rows: Record<string, unknown>[];
  label?: string;
}

export const ExportButton: React.FC<ExportButtonProps> = ({ filename, rows, label = "Export" }) => (
  <button
    type="button"
    className="export-button"
    disabled={rows.length === 0}
    onClick={() => downloadCsv(filename, toCsv(rows))}
  >
    <span aria-hidden="true">↓</span> {label}
  </button>
);
