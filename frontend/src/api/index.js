import axios from "axios";

const client = axios.create({ baseURL: "/api" });

export async function addNote(text, title) {
  const { data } = await client.post("/notes", { text, title: title || undefined });
  return data;
}

export async function uploadFiles(formData) {
  const { data } = await client.post("/ingest", formData);
  return data;
}

export async function searchNotes(query, tag, topK = 5) {
  const { data } = await client.get("/search", {
    params: { query, tag: tag || undefined, top_k: topK },
  });
  return data;
}

export async function askQuestion(question) {
  const { data } = await client.post("/ask", { question });
  return data;
}

export async function getStatus() {
  const { data } = await client.get("/status");
  return data;
}

export async function getConnections() {
  const { data } = await client.get("/connections");
  return data;
}

export async function getDigest(weekly = false) {
  const { data } = await client.get("/digest", { params: { weekly } });
  return data;
}

export async function getReview(limit = 5) {
  const { data } = await client.get("/review", { params: { limit } });
  return data;
}

// ============ 会话管理 ============

export async function createSession(title) {
  const { data } = await client.post("/sessions", { title });
  return data;
}

export async function listSessions() {
  const { data } = await client.get("/sessions");
  return data;
}

export async function getSessionMessages(sessionId) {
  const { data } = await client.get(`/sessions/${sessionId}/messages`);
  return data;
}

export async function deleteSession(sessionId) {
  const { data } = await client.delete(`/sessions/${sessionId}`);
  return data;
}

export async function listFragments() {
  const { data } = await client.get("/fragments");
  return data;
}
