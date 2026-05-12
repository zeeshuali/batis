import React from "react";
import { BarChart as RBarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Cell } from "recharts";

export interface BarPoint {
  label: string;
  value: number;
  color?: string;
}

export interface BarChartProps {
  data:    BarPoint[];
  height?: number;
  /** When set, bars use this color; otherwise each bar's `.color` is used,
   *  falling back to brand blue. */
  color?:  string;
}

export const BarChart: React.FC<BarChartProps> = ({ data, height = 220, color }) => (
  <ResponsiveContainer width="100%" height={height}>
    <RBarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
      <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} tickLine={false} interval={0} angle={-30} textAnchor="end" height={50} />
      <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
      <Tooltip contentStyle={{ background: "#1a2334", border: "1px solid #283448", borderRadius: 8, fontSize: 12 }} />
      <Bar dataKey="value" radius={[4, 4, 0, 0]} isAnimationActive={false}>
        {data.map((d, i) => (
          <Cell key={i} fill={color ?? d.color ?? "#3b82f6"} />
        ))}
      </Bar>
    </RBarChart>
  </ResponsiveContainer>
);
