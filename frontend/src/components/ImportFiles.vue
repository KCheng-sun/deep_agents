<script setup>
import { ref, onMounted } from "vue";
import { uploadFiles } from "../api/index.js";
import axios from "axios";

const result = ref("");
const loading = ref(false);
// 文件监听状态
const watch = ref({ running: false, watch_dir: "", recent_events: [] });
const watchLoading = ref(false);

async function onFileChange(e) {
  const files = e.target.files;
  if (!files.length) return;

  loading.value = true;
  result.value = "";

  const formData = new FormData();
  for (const f of files) {
    if (f.name.endsWith(".md")) formData.append("file", f);
  }

  try {
    const res = await uploadFiles(formData);
    result.value = `✅ ${res.message}`;
  } catch (e) {
    result.value = `❌ 失败: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

async function refreshWatch() {
  try {
    const { data } = await axios.get("/api/watch");
    watch.value = data;
  } catch (e) {
    console.error(e);
  }
}

async function toggleWatch() {
  watchLoading.value = true;
  try {
    if (watch.value.running) {
      const { data } = await axios.post("/api/watch/stop");
      watch.value = data;
    } else {
      const { data } = await axios.post("/api/watch/start");
      watch.value = data;
    }
  } catch (e) {
    console.error(e);
  } finally {
    watchLoading.value = false;
  }
}

onMounted(refreshWatch);
</script>

<template>
  <div>
    <h3 style="margin-bottom: 16px">导入 Markdown 文件</h3>
    <p class="hint">支持拖拽或点击选择多个 .md 文件</p>
    <label class="drop-zone">
      <input
        type="file"
        accept=".md"
        multiple
        style="display: none"
        @change="onFileChange"
      />
      <span>{{ loading ? "导入中..." : "📥 选择文件" }}</span>
    </label>
    <div v-if="result" class="result">{{ result }}</div>

    <!-- 文件监听 -->
    <div class="watch-section">
      <div class="watch-header">
        <h4>👀 自动监听</h4>
        <span :class="['watch-status', watch.running ? 'on' : 'off']">
          {{ watch.running ? "● 监听中" : "○ 已停止" }}
        </span>
        <button class="btn-toggle" :disabled="watchLoading" @click="toggleWatch">
          {{ watch.running ? "停止" : "启动" }}
        </button>
      </div>
      <p class="watch-dir">监听目录: {{ watch.watch_dir }}</p>
      <p class="watch-hint">把 .md 文件放入该目录，系统会自动摄入（无需手动上传）</p>

      <div v-if="watch.recent_events && watch.recent_events.length" class="watch-events">
        <div v-for="(ev, i) in watch.recent_events" :key="i" class="watch-event-row">
          <span class="event-time">{{ ev.time }}</span>
          <span class="event-file">{{ ev.file }}</span>
          <code class="event-id">{{ ev.note_id }}</code>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hint {
  color: var(--text-dim);
  font-size: 14px;
  margin-bottom: 16px;
}
.drop-zone {
  display: block;
  padding: 40px;
  border: 2px dashed var(--border);
  border-radius: 12px;
  text-align: center;
  cursor: pointer;
  font-size: 16px;
  color: var(--primary);
  background: var(--bg-card);
  transition: border-color 0.15s;
}
.drop-zone:hover {
  border-color: var(--primary);
}
.result {
  margin-top: 16px;
  padding: 10px 14px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 8px;
  font-size: 14px;
  color: var(--success);
}

/* 监听区域 */
.watch-section {
  margin-top: 32px;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.watch-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.watch-header h4 {
  font-size: 15px;
}
.watch-status {
  font-size: 13px;
  font-weight: 600;
}
.watch-status.on {
  color: var(--success);
}
.watch-status.off {
  color: var(--text-faint);
}
.btn-toggle {
  margin-left: auto;
  padding: 7px 18px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}
.btn-toggle:hover {
  opacity: 0.85;
}
.watch-dir {
  font-size: 13px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  margin-bottom: 4px;
}
.watch-hint {
  font-size: 13px;
  color: var(--text-faint);
  margin-bottom: 12px;
}
.watch-events {
  max-height: 180px;
  overflow-y: auto;
}
.watch-event-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.event-time {
  color: var(--text-faint);
  font-family: var(--font-mono);
}
.event-file {
  color: var(--text-main);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.event-id {
  font-size: 12px;
  color: var(--text-faint);
}
</style>
