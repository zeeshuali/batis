import React from "react";
import "./primitives.css";

export interface SectionErrorProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export const SectionError: React.FC<SectionErrorProps> = ({ title = "Couldn't load this section", message, onRetry }) => (
  <div className="section-error" role="alert">
    <p className="section-error__title">{title}</p>
    <p className="section-error__msg">{message}</p>
    {onRetry && (
      <button type="button" className="section-error__retry" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);
