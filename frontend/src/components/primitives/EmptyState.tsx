import React from "react";
import "./primitives.css";

export const EmptyState: React.FC<{ message: string; hint?: string }> = ({ message, hint }) => (
  <div className="empty-state">
    <p className="empty-state__msg">{message}</p>
    {hint && <p className="empty-state__hint">{hint}</p>}
  </div>
);
