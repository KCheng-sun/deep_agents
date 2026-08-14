<script setup>
import { ref, onMounted } from "vue";
import axios from "axios";

const feeds = ref([]);
const newUrl = ref("");
const loading = ref(false);
const message = ref("");

async function refresh() {
  try {
    const { data } = await axios.get("/api/rss");
    feeds.value = data;
  } catch (e) {
    console.error(e);
  }
}

async function addFeed() {
  const url = newUrl.value.trim();
  if (!url) return;
  loading.value = true;
  message.value = "";
  try {
    const { data } = await axios.post("/api/rss", { url });
    message.value = `✅ 已添加并拉取，新增摄入 ${data.new_entries} 条`;
    newUrl.value = "";
    await refresh();
  } catch (e) {
    message.value = `❌ 添加失败: ${e.response?.data?.detail || e.message}`;
  } finally {
    loading.value = false;
  }
}

async function fetchAll() {
  loading.value = true;
  message.value = "";
  try {
    const { data } = await axios.post("/api/rss/fetch");
    message.value = `📡 检查 ${data.feeds_checked} 个源，新增摄入 ${data.new_entries} 条`;
    await refresh();
  } catch (e) {
    message.value = `❌ 拉取失败: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

async function removeFeed(id) {
  if (!confirm("确定删除这个订阅源？")) return;
  try {
    await axios.delete(`/api/rss/${id}`);
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
      <p class="hint">订阅 RSS 源，新文章自动摄入知识库（打标签、建关联）</p>
      <button class="btn" :disabled="loading" @click="fetchAll">
        {{ loading ? "拉取中..." : "📡 立即拉取" }}
      </button>
    </div>

    <!-- 添加订阅源 -->
    <div class="add-row">
      <input
        v-model="newUrl"
        class="input"
        placeholder="输入 RSS/Atom 订阅源 URL，如 https://blog.example.com/feed.xml"
        @keyup.enter="addFeed"
      />
      <button class="btn" :disabled="loading || !newUrl.trim()" @click="addFeed">
        添加
      </button>
    </div>

    <div v-if="message" class="message">{{ message }}</div>

    <!-- 订阅源列表 -->
    <div v-if="!feeds.length && !loading" class="empty">
      <div class="empty-icon">📡</div>
      <p>还没有订阅源</p>
    </div>

    <div v-for="f in feeds" :key="f.id" class="feed-card">
      <div class="feed-head">
        <span class="feed-title">{{ f.title || f.url }}</span>
        <button class="delete-btn" title="删除" @click="removeFeed(f.id)">✕</button>
      </div>
      <div class="feed-meta">
        <span class="feed-url">{{ f.url }}</span>
        <span class="feed-stats">累计 {{ f.entry_count }} 条</span>
        <span class="feed-stats">
          上次拉取: {{ f.last_fetched_at ? f.last_fetched_at.slice(0, 10) : "从未" }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.hint {
  color: var(--text-dim);
  font-size: 14px;
  flex: 1;
}
.add-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: var(--bg-card);
  color: var(--text-main);
}
.input:focus {
  border-color: var(--primary);
}
.btn {
  padding: 10px 20px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  flex-shrink: 0;
}
.btn:hover:not(:disabled) {
  opacity: 0.85;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.message {
  padding: 10px 14px;
  margin-bottom: 16px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 8px;
  font-size: 14px;
  color: var(--success);
}
.empty {
  text-align: center;
  padding: 50px 0;
  color: var(--text-dim);
}
.empty-icon {
  font-size: 36px;
  margin-bottom: 10px;
}
.feed-card {
  padding: 14px 16px;
  margin-bottom: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.feed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.feed-title {
  font-weight: 600;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 10px;
}
.delete-btn {
  border: none;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
  padding: 4px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.delete-btn:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}
.feed-meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--text-faint);
}
.feed-url {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
}
.feed-stats {
  flex-shrink: 0;
}
</style>
