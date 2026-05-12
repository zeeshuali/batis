import React from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";

export interface TrendPoint {
  x: string;
  y: number | null;
}

export interface TrendChartProps {
  data:    TrendPoint[];
  yLabel?: string;
  color?:  string;
  height?: number;
}

export const TrendChart: React.FC<TrendChartProps> = ({ data, yLabel, color = "#3b82f6", height = 200 }) => (
  <ResponsiveContainer width="100%" height={height}>
    <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
      <XAxis dataKey="x" stroke="#94a3b8" fontSize={11} tickLine={false} />
      <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", fill: "#94a3b8", fontSize: 11 } : undefined} />
      <Tooltip contentStyle={{ background: "#1a2334", border: "1px solid #283448", borderRadius: 8, fontSize: 12 }} />
      <Line type="monotone" dataKey="y" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
    </LineChart>
  </ResponsiveContainer>
);
