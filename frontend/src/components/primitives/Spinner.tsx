import React from "react";
import "./primitives.css";

export const Spinner: React.FC<{ size?: "sm" | "md" }> = ({ size = "md" }) => (
  <span className={`spinner spinner--${size}`} role="progressbar" aria-label="Loading" />
);
