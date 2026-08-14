<script setup>
import { ref, onMounted, computed } from "vue";
import axios from "axios";

const items = ref([]);
const loading = ref(false);
const currentIndex = ref(0);
const revealed = ref(false); // 是否展开答案
const noteContent = ref(""); // 展开后从后端取全文

const current = computed(() => items.value[currentIndex.value] || null);
const progress = computed(() =>
  items.value.length ? `${currentIndex.value + 1}/${items.value.length}` : "0/0"
);

async function refresh() {
  loading.value = true;
  try {
    const { data } = await axios.get("/api/review", { params: { limit: 20 } });
    items.value = data.items || [];
    currentIndex.value = 0;
    revealed.value = false;
    noteContent.value = "";
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

async function reveal() {
  if (revealed.value) return;
  // 精确取回笔记全文（后端 get_note_chunks 按 metadata 过滤）
  try {
    const { data } = await axios.get(`/api/notes/${current.value.note_id}/content`);
    noteContent.value = data.content || "(内容为空)";
  } catch (e) {
    noteContent.value = "(内容取回失败)";
  }
  revealed.value = true;
}

async function rate(quality) {
  if (!current.value) return;
  try {
    await axios.post("/api/review/record", {
      note_id: current.value.note_id,
      quality,
    });
  } catch (e) {
    console.error(e);
  }
  // 下一张卡
  revealed.value = false;
  noteContent.value = "";
  if (currentIndex.value < items.value.length - 1) {
    currentIndex.value++;
  } else {
    await refresh(); // 一轮完成，重新拉取
  }
}

onMounted(refresh);
</script>

<template>
  <div class="review-page">
    <div class="header-row">
      <p class="hint">先回想，再展开验证，最后诚实评分——SM-2 会据此安排下次复习</p>
      <button class="btn-refresh" :disabled="loading" @click="refresh">
        {{ loading ? "加载中..." : "🔄 刷新" }}
      </button>
    </div>

    <!-- 完成态 -->
    <div v-if="!loading && items.length === 0" class="done-state">
      <div class="done-icon">🎉</div>
      <p>今日复习完成！</p>
      <p class="done-sub">没有到期的卡片。新笔记摄入后会自动加入复习队列</p>
    </div>

    <!-- 复习卡片 -->
    <div v-else-if="current" class="card-wrap">
      <div class="card-progress">{{ progress }}</div>

      <div class="card">
        <div class="card-head">
          <span :class="['card-badge', current.is_new ? 'new' : 'review']">
            {{ current.is_new ? "🆕 新卡片" : `🔁 第 ${current.review_count} 次复习` }}
          </span>
          <span v-if="!current.is_new" class="card-meta">
            熟练度 {{ current.ease_factor?.toFixed?.(2) ?? "2.50" }} · 间隔 {{ current.interval_days }} 天
          </span>
        </div>

        <div class="card-title">{{ current.title }}</div>

        <!-- 未展开：提示回想 -->
        <div v-if="!revealed" class="card-hint">
          🤔 先试着回想这篇笔记讲了什么...
        </div>

        <!-- 已展开：显示内容预览 -->
        <div v-else class="card-content">{{ noteContent }}</div>

        <div class="card-actions">
          <button v-if="!revealed" class="btn-reveal" @click="reveal">
            👁 显示内容
          </button>
          <template v-else>
            <button class="rate-btn forget" @click="rate(1)">😵 忘记</button>
            <button class="rate-btn hard" @click="rate(3)">😅 困难</button>
            <button class="rate-btn good" @click="rate(4)">🙂 良好</button>
            <button class="rate-btn easy" @click="rate(5)">🤩 简单</button>
          </template>
        </div>
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
.done-state {
  text-align: center;
  padding: 70px 0;
  color: var(--text-dim);
}
.done-icon {
  font-size: 44px;
  margin-bottom: 12px;
}
.done-sub {
  font-size: 13px;
  color: var(--text-faint);
  margin-top: 6px;
}
.card-wrap {
  max-width: 560px;
  margin: 0 auto;
}
.card-progress {
  text-align: center;
  font-size: 13px;
  color: var(--text-faint);
  font-family: var(--font-mono);
  margin-bottom: 10px;
}
.card {
  padding: 24px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.card-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 12px;
}
.card-badge.new {
  background: rgba(0, 132, 255, 0.1);
  color: var(--primary);
}
.card-badge.review {
  background: rgba(16, 185, 129, 0.1);
  color: var(--success);
}
.card-meta {
  font-size: 12px;
  color: var(--text-faint);
  font-family: var(--font-mono);
}
.card-title {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-main);
}
.card-hint {
  padding: 20px;
  text-align: center;
  font-size: 14px;
  color: var(--text-faint);
  background: var(--bg-panel);
  border-radius: 10px;
  margin-bottom: 16px;
}
.card-content {
  padding: 16px;
  font-size: 14px;
  color: var(--text-dim);
  line-height: 1.7;
  background: var(--bg-panel);
  border-radius: 10px;
  margin-bottom: 16px;
  max-height: 240px;
  overflow-y: auto;
  white-space: pre-wrap;
}
.card-actions {
  display: flex;
  gap: 8px;
}
.btn-reveal {
  flex: 1;
  padding: 10px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  cursor: pointer;
}
.btn-reveal:hover {
  opacity: 0.85;
}
.rate-btn {
  flex: 1;
  padding: 10px 6px;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 13px;
  cursor: pointer;
  background: var(--bg-panel);
  transition: all 0.12s;
}
.rate-btn.forget:hover {
  border-color: var(--danger);
  background: rgba(239, 68, 68, 0.08);
}
.rate-btn.hard:hover {
  border-color: #f39c12;
  background: rgba(243, 156, 18, 0.08);
}
.rate-btn.good:hover {
  border-color: var(--success);
  background: rgba(16, 185, 129, 0.08);
}
.rate-btn.easy:hover {
  border-color: var(--primary);
  background: rgba(0, 132, 255, 0.08);
}
</style>
