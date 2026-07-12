import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: `${API_URL}/api/v1`,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// Unwrap the { data, error } envelope
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error.response?.data?.detail ??
      error.response?.data?.error ??
      error.message ??
      "Unknown error";
    return Promise.reject(new Error(message));
  }
);
