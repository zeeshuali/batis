import React from "react";
import { FilterProvider } from "./context/FilterContext";
import { SelectionProvider } from "./context/SelectionContext";
import { AppShell } from "./components/AppShell";

export const App: React.FC = () => (
  <FilterProvider>
    <SelectionProvider>
      <AppShell />
    </SelectionProvider>
  </FilterProvider>
);
