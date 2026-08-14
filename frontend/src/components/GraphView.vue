<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import * as echarts from "echarts";
import axios from "axios";

const chartEl = ref(null);
const chart = ref(null);
const loading = ref(true);
const selectedNode = ref(null);
const empty = ref(false);

// 关联类型 → 边颜色
const RELATION_COLORS = {
  related: "#94a3b8",
  extends: "#0084ff",
  contradicts: "#ef4444",
  references: "#10b981",
};

const RELATION_LABELS = {
  related: "相关",
  extends: "延续",
  contradicts: "矛盾",
  references: "引用",
};

async function refresh() {
  loading.value = true;
  try {
    const { data } = await axios.get("/api/graph");
    renderGraph(data);
    empty.value = data.nodes.length === 0;
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function renderGraph(data) {
  if (!chart.value) {
    chart.value = echarts.init(chartEl.value);
    chart.value.on("click", (params) => {
      if (params.dataType === "node") {
        showNodeDetail(params.data);
      }
    });
  }

  const maxDegree = Math.max(1, ...data.nodes.map((n) => n.degree));
  // 无关联的孤立节点不显示（图谱聚焦关联网络）
  const connectedIds = new Set();
  data.edges.forEach((e) => {
    connectedIds.add(e.source);
    connectedIds.add(e.target);
  });

  // 分类调色板——与图例一一对应
  const CATEGORY_COLORS = [
    "#0084ff", "#00b8d4", "#10b981", "#f59e0b",
    "#8b5cf6", "#ef4444", "#ec4899", "#64748b",
  ];

  const nodes = data.nodes
    .filter((n) => connectedIds.has(n.id))
    .map((n) => ({
      id: n.id,
      name: n.title,
      symbolSize: 14 + (n.degree / maxDegree) * 22, // 大小 = 关联数
      category: n.tags[0] || "未分类",
      value: n.degree,
      label: { show: true, fontSize: 11, color: "#1a2c45" },
      // 详情数据挂载在节点上
      _detail: n,
    }));

  const edges = data.edges.map((e) => ({
    source: e.source,
    target: e.target,
    lineStyle: {
      color: RELATION_COLORS[e.relation_type] || "#94a3b8",
      width: 1 + e.strength * 2,
      curveness: 0.1,
      opacity: 0.7,
    },
    _detail: e,
  }));

  // 图例——每个分类显式指定颜色，保证图例与节点颜色一致
  const categories = [...new Set(nodes.map((n) => n.category))].map((c, i) => ({
    name: c,
    itemStyle: { color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] },
  }));

  chart.value.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        if (p.dataType === "edge") {
          const d = p.data._detail || {};
          const label = RELATION_LABELS[d.relation_type] || d.relation_type;
          return `${label}关系<br/>强度: ${Math.round((d.strength || 0) * 100)}%${
            d.description ? `<br/>${d.description.slice(0, 80)}` : ""
          }`;
        }
        const d = p.data._detail || {};
        return `<b>${d.title}</b><br/>标签: ${(d.tags || []).join(", ") || "无"}<br/>关联数: ${d.degree}<br/>${d.date}`;
      },
    },
    legend: [{ data: categories.map((c) => c.name), bottom: 10 }],
    series: [
      {
        type: "graph",
        layout: "force",
        data: nodes,
        links: edges,
        roam: true,
        draggable: true,
        categories,
        force: {
          repulsion: 260,
          edgeLength: [80, 200],
          gravity: 0.08,
        },
        emphasis: {
          focus: "adjacency",
          lineStyle: { width: 3 },
        },
        label: {
          show: true,
          position: "right",
          formatter: (p) => p.name,
        },
      },
    ],
  });
}

function showNodeDetail(node) {
  selectedNode.value = node;
}

function handleResize() {
  chart.value?.resize();
}

onMounted(() => {
  refresh();
  window.addEventListener("resize", handleResize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chart.value?.dispose();
});
</script>

<template>
  <div class="graph-page">
    <div class="header-row">
      <p class="hint">
        节点大小 = 关联数量；边颜色 = 关联类型；点击节点查看详情，滚轮缩放，拖拽平移
      </p>
      <button class="btn-refresh" :disabled="loading" @click="refresh">
        {{ loading ? "加载中..." : "🔄 刷新" }}
      </button>
    </div>

    <!-- 图例 -->
    <div class="legend-row">
      <span v-for="(color, type) in RELATION_COLORS" :key="type" class="legend-item">
        <span class="legend-line" :style="{ background: color }"></span>
        {{ RELATION_LABELS[type] }}
      </span>
    </div>

    <div v-if="empty && !loading" class="empty">
      <div class="empty-icon">🕸️</div>
      <p>还没有关联数据</p>
      <p class="empty-sub">摄入多篇同主题笔记后，AI 会自动发现它们之间的关联</p>
    </div>

    <div v-show="!empty" ref="chartEl" class="chart-box"></div>

    <!-- 选中节点详情 -->
    <div v-if="selectedNode" class="node-panel">
      <div class="node-panel-head">
        <span class="node-title">{{ selectedNode._detail.title }}</span>
        <button class="close-btn" @click="selectedNode = null">✕</button>
      </div>
      <div class="node-meta">
        <div>🏷️ 标签: {{ selectedNode._detail.tags.join(", ") || "无" }}</div>
        <div>🔗 关联数: {{ selectedNode._detail.degree }}</div>
        <div>📅 {{ selectedNode._detail.date }}</div>
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
  margin-bottom: 10px;
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
.legend-row {
  display: flex;
  gap: 16px;
  margin-bottom: 14px;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-dim);
}
.legend-line {
  width: 18px;
  height: 3px;
  border-radius: 2px;
}
.chart-box {
  height: calc(100vh - 260px);
  min-height: 480px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-card);
}
.empty {
  text-align: center;
  padding: 80px 0;
  color: var(--text-dim);
}
.empty-icon {
  font-size: 44px;
  margin-bottom: 12px;
}
.empty-sub {
  font-size: 13px;
  color: var(--text-faint);
  margin-top: 6px;
}
.node-panel {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 300px;
  padding: 16px;
  background: var(--bg-panel);
  border: 1px solid var(--border-glow);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
  z-index: 20;
}
.node-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.node-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  margin-right: 8px;
}
.close-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-faint);
  font-size: 14px;
}
.node-meta {
  font-size: 13px;
  color: var(--text-dim);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
