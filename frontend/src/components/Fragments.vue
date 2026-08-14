<script setup>
import { ref, onMounted } from "vue";
import { listFragments } from "../api/index.js";
import axios from "axios";

const fragments = ref([]);
const loading = ref(false);

async function refresh() {
  loading.value = true;
  try {
    fragments.value = await listFragments();
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

async function removeFragment(id) {
  if (!confirm("确定删除这条知识片段？")) return;
  try {
    await axios.delete(`/api/fragments/${id}`);
    await refresh();
  } catch (e) {
    console.error(e);
  }
}

onMounted(refresh);
</script>

<template>
  <div>
    <div class="header-row">
      <p class="hint">对话中经你确认保存的结论沉淀在这里，问答时 Agent 可以引用它们</p>
      <button class="btn-refresh" :disabled="loading" @click="refresh">
        {{ loading ? "刷新中..." : "🔄 刷新" }}
      </button>
    </div>

    <div v-if="!loading && fragments.length === 0" class="empty">
      <div class="empty-icon">💡</div>
      <p>还没有保存的知识片段</p>
      <p class="empty-sub">在问答中，当 Agent 提议保存知识时点击「保存」即可沉淀到这里</p>
    </div>

    <div v-for="f in fragments" :key="f.id" class="fragment-card">
      <div class="fragment-head">
        <span class="fragment-title">{{ f.title }}</span>
        <span class="fragment-date">{{ f.created_at.slice(0, 10) }}</span>
        <button class="delete-btn" title="删除片段" @click="removeFragment(f.id)">✕</button>
      </div>
      <div class="fragment-content">{{ f.content }}</div>
    </div>
  </div>
</template>

<style scoped>
.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.hint {
  color: var(--text-dim);
  font-size: 14px;
  flex: 1;
}
.btn-refresh {
  padding: 8px 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  flex-shrink: 0;
}
.btn-refresh:hover {
  opacity: 0.85;
}
.empty {
  text-align: center;
  padding: 60px 0;
  color: var(--text-dim);
}
.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}
.empty-sub {
  font-size: 13px;
  color: var(--text-faint);
  margin-top: 6px;
}
.fragment-card {
  padding: 16px;
  margin-bottom: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.fragment-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.fragment-title {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-main);
  flex: 1;
}
.fragment-date {
  font-size: 12px;
  color: var(--text-faint);
  font-family: var(--font-mono);
}
.delete-btn {
  border: none;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
  padding: 4px 6px;
  border-radius: 4px;
  transition: all 0.12s;
}
.delete-btn:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}
.fragment-content {
  font-size: 14px;
  color: var(--text-dim);
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
