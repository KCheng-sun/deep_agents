<script setup>
import { ref } from "vue";
import { searchNotes } from "../api/index.js";

const query = ref("");
const tag = ref("");
const topK = ref(5);
const results = ref([]);
const total = ref(0);
const loading = ref(false);

async function search() {
  if (!query.value.trim()) return;
  loading.value = true;
  try {
    const data = await searchNotes(query.value, tag.value, topK.value);
    results.value = data.results;
    total.value = data.total;
  } catch (e) {
    results.value = [];
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div>
    <h3 style="margin-bottom: 16px">语义搜索</h3>
    <div class="search-row">
      <input
        v-model="query"
        class="input search-input"
        placeholder="输入关键词..."
        @keyup.enter="search"
      />
      <input
        v-model="tag"
        class="input tag-input"
        placeholder="标签（可选）"
        @keyup.enter="search"
      />
      <select v-model.number="topK" class="select">
        <option :value="3">3 条</option>
        <option :value="5">5 条</option>
        <option :value="10">10 条</option>
        <option :value="20">20 条</option>
      </select>
      <button class="btn" :disabled="loading" @click="search">
        {{ loading ? "..." : "🔍 搜索" }}
      </button>
    </div>

    <div v-if="total > 0" class="result-count">共 {{ total }} 条结果</div>

    <div v-for="r in results" :key="r.note_id" class="result-item">
      <div class="result-header">
        <span class="score">[{{ r.score }}]</span>
        <span class="title">{{ r.title }}</span>
      </div>
      <div class="tags" v-if="r.tags.length">
        🏷️ {{ r.tags.join(" · ") }}
      </div>
      <div class="preview">{{ r.content_preview }}...</div>
      <code class="note-id">{{ r.note_id }}</code>
    </div>

    <div v-if="!loading && results.length === 0 && query" class="empty">
      没有找到相关笔记
    </div>
  </div>
</template>

<style scoped>
.search-row {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}
.input {
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 15px;
  outline: none;
  background: var(--bg-card);
  color: var(--text-main);
}
.input:focus {
  border-color: var(--primary);
}
.search-input {
  flex: 3;
}
.tag-input {
  flex: 1;
}
.select {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: var(--bg-card);
  color: var(--text-main);
}
.btn {
  padding: 10px 20px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  cursor: pointer;
}
.btn:hover {
  opacity: 0.85;
}
.result-count {
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 16px;
}
.result-item {
  padding: 16px;
  margin-bottom: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.result-header {
  margin-bottom: 6px;
}
.score {
  font-weight: 700;
  color: var(--primary);
  font-size: 13px;
  font-family: var(--font-mono);
}
.title {
  font-weight: 600;
  font-size: 16px;
}
.tags {
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.preview {
  font-size: 14px;
  color: var(--text-main);
  line-height: 1.5;
}
.note-id {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-faint);
  font-family: var(--font-mono);
}
.empty {
  text-align: center;
  color: var(--text-dim);
  padding: 40px;
}
</style>
