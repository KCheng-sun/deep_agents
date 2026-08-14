<script setup>
import { ref, onMounted } from "vue";
import { getStatus, getDigest, getReview } from "../api/index.js";
import axios from "axios";

const status = ref(null);
const digest = ref(null);
const review = ref(null);
const scheduler = ref([]);
const loading = ref(true);

const RELATION_ICONS = { related: "🔗", extends: "➡️", contradicts: "⚡", references: "📖" };

async function refresh() {
  loading.value = true;
  try {
    const [s, d, r, sch] = await Promise.all([
      getStatus(),
      getDigest(false),
      getReview(5),
      axios.get("/api/scheduler").then((res) => res.data),
    ]);
    status.value = s;
    digest.value = d;
    review.value = r;
    scheduler.value = sch;
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function formatTime(iso) {
  const d = new Date(iso);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

onMounted(refresh);
</script>

<template>
  <div>
    <div class="header-row">
      <h3>知识库概览</h3>
      <button class="btn-refresh" :disabled="loading" @click="refresh">
        {{ loading ? "刷新中..." : "🔄 刷新" }}
      </button>
    </div>

    <div v-if="status" class="stats-grid">
      <div class="stat-card">
        <div class="stat-num">{{ status.note_count }}</div>
        <div class="stat-label">笔记总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ status.chunk_count }}</div>
        <div class="stat-label">分块总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ status.tag_count }}</div>
        <div class="stat-label">AI 标签</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ status.connection_count }}</div>
        <div class="stat-label">AI 关联</div>
      </div>
    </div>

    <!-- 热门标签 -->
    <div v-if="status?.top_tags?.length" class="section">
      <h4>🏷️ 热门标签</h4>
      <div class="tag-list">
        <span v-for="t in status.top_tags" :key="t.name" class="tag-chip">
          {{ t.name }} <small>{{ t.count }}</small>
        </span>
      </div>
    </div>

    <!-- 最近笔记 -->
    <div v-if="status?.recent_notes?.length" class="section">
      <h4>📝 最近摄入</h4>
      <div v-for="n in status.recent_notes" :key="n.note_id" class="note-row">
        <span class="note-date">[{{ n.date }}]</span>
        <span class="note-title">{{ n.title }}</span>
        <span v-if="n.tags.length" class="note-tags">
          🏷️ {{ n.tags.slice(0, 3).join(" · ") }}
        </span>
      </div>
    </div>

    <!-- 关联 -->
    <div v-if="status?.connections?.length" class="section">
      <h4>🔗 关联一览</h4>
      <div v-for="c in status.connections" :key="c.source_title + c.target_title" class="conn-row">
        {{ RELATION_ICONS[c.relation_type] || "🔗" }}
        [{{ c.relation_type }}]
        <strong>{{ c.source_title }}</strong> → <strong>{{ c.target_title }}</strong>
        <div v-if="c.description" class="conn-desc">{{ c.description }}</div>
      </div>
    </div>

    <!-- 每日摘要 -->
    <div v-if="digest?.content" class="section digest">
      <h4>📅 知识摘要</h4>
      <div class="digest-content" v-html="digest.content
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>')"></div>
    </div>

    <!-- 复习提醒 -->
    <div v-if="review?.items?.length" class="section">
      <h4>📖 需要复习 ({{ review.total }})</h4>
      <div v-for="r in review.items" :key="r.note_id" class="review-row">
        <span :class="['dot', r.freshness < 0.2 ? 'red' : r.freshness < 0.3 ? 'yellow' : 'green']"></span>
        [{{ r.date }}] {{ r.title }}
        <span class="freshness">{{ (r.freshness * 100).toFixed(0) }}%</span>
      </div>
    </div>

    <!-- 定时任务状态 -->
    <div v-if="scheduler.length" class="section">
      <h4>⏰ 定时任务</h4>
      <div v-for="t in scheduler" :key="t.name" class="task-row">
        <div class="task-info">
          <span class="task-name">{{ t.description }}</span>
          <span class="task-result">{{ t.last_result || "尚未运行" }}</span>
        </div>
        <div class="task-meta">
          <span>上次: {{ t.last_run_at ? formatTime(t.last_run_at) : "—" }}</span>
          <span>下次: {{ t.next_run_at ? formatTime(t.next_run_at) : "—" }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.btn-refresh {
  padding: 8px 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}
.btn-refresh:hover {
  opacity: 0.85;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}
.stat-card {
  text-align: center;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.stat-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono);
}
.stat-label {
  font-size: 13px;
  color: var(--text-dim);
  margin-top: 4px;
}
.section {
  margin-bottom: 24px;
}
.section h4 {
  margin-bottom: 12px;
  font-size: 16px;
  color: var(--text-main);
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag-chip {
  padding: 6px 14px;
  background: rgba(0, 132, 255, 0.08);
  border: 1px solid var(--border-glow);
  color: var(--primary);
  border-radius: 20px;
  font-size: 14px;
}
.tag-chip small {
  color: var(--text-dim);
}
.note-row,
.review-row {
  padding: 8px 0;
  font-size: 14px;
  border-bottom: 1px solid var(--border);
}
.note-date {
  color: var(--text-dim);
  margin-right: 8px;
}
.note-tags {
  font-size: 13px;
  color: var(--text-dim);
  margin-left: 8px;
}
.conn-row {
  padding: 8px 0;
  font-size: 14px;
  border-bottom: 1px solid var(--border);
}
.conn-desc {
  font-size: 13px;
  color: var(--text-dim);
  font-style: italic;
  margin-top: 4px;
}
.digest {
  padding: 20px;
  background: var(--bg-card);
  border-radius: 12px;
  border: 1px solid var(--border-glow);
}
.digest-content {
  font-size: 14px;
  line-height: 1.7;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}
.dot.red { background: var(--danger); }
.dot.yellow { background: #f39c12; }
.dot.green { background: var(--success); }
.freshness {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-dim);
}
.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.task-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
}
.task-name {
  font-size: 14px;
  font-weight: 500;
}
.task-result {
  font-size: 12px;
  color: var(--text-dim);
}
.task-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  color: var(--text-faint);
  font-family: var(--font-mono);
  text-align: right;
  flex-shrink: 0;
}
</style>
