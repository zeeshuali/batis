import React from "react";
import { ThemeProvider } from "./context/ThemeContext";
import { AgenciesProvider } from "./context/AgenciesContext";
import { FilterProvider } from "./context/FilterContext";
import { SelectionProvider } from "./context/SelectionContext";
import { AppShell } from "./components/AppShell";

export const App: React.FC = () => (
  <ThemeProvider>
    <AgenciesProvider>
      <FilterProvider>
        <SelectionProvider>
          <AppShell />
        </SelectionProvider>
      </FilterProvider>
    </AgenciesProvider>
  </ThemeProvider>
);
