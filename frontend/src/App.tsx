import React from "react";
import { ThemeProvider } from "./context/ThemeContext";
import { FilterProvider } from "./context/FilterContext";
import { SelectionProvider } from "./context/SelectionContext";
import { AppShell } from "./components/AppShell";

export const App: React.FC = () => (
  <ThemeProvider>
    <FilterProvider>
      <SelectionProvider>
        <AppShell />
      </SelectionProvider>
    </FilterProvider>
  </ThemeProvider>
);
