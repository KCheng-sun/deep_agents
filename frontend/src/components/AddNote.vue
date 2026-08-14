<script setup>
import { ref } from "vue";
import { addNote } from "../api/index.js";

const title = ref("");
const text = ref("");
const result = ref("");
const loading = ref(false);

async function submit() {
  if (!text.value.trim()) return;
  loading.value = true;
  try {
    const res = await addNote(text.value, title.value);
    result.value = `✅ ${res.message}: ${res.note_id}`;
    title.value = "";
    text.value = "";
  } catch (e) {
    result.value = `❌ 失败: ${e.message}`;
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div>
    <div class="form-group">
      <input
        v-model="title"
        type="text"
        class="input"
        placeholder="标题（可选，留空自动提取）"
      />
    </div>
    <div class="form-group">
      <textarea
        v-model="text"
        class="textarea"
        rows="6"
        placeholder="开始写你的想法..."
      ></textarea>
    </div>
    <button class="btn" :disabled="loading" @click="submit">
      {{ loading ? "摄入中..." : "✍️ 摄入笔记" }}
    </button>
    <div v-if="result" class="result">{{ result }}</div>
  </div>
</template>

<style scoped>
.form-group {
  margin-bottom: 12px;
}
.input,
.textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 15px;
  font-family: inherit;
  outline: none;
  background: var(--bg-card);
  color: var(--text-main);
  transition: border-color 0.15s;
}
.input:focus,
.textarea:focus {
  border-color: var(--primary);
}
.btn {
  padding: 10px 24px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn:hover {
  opacity: 0.85;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.result {
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 8px;
  font-size: 14px;
  color: var(--success);
}
</style>
