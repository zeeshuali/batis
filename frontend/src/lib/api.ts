import axios, { AxiosInstance } from "axios";

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
const API_KEY: string = (import.meta.env.VITE_API_KEY as string) || "";

export function apiHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: apiHeaders(),
  timeout: 30000,
});
