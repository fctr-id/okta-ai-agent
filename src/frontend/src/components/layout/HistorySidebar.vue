<template>
  <aside class="history-sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <!-- Header -->
    <div class="sidebar-header" @click="isCollapsed = !isCollapsed">
      <div v-if="!isCollapsed" class="sidebar-title">
        <v-icon icon="mdi-history" size="15" class="title-icon" />
        <span>Activity</span>
        <span class="count-pill">{{ history.length }}</span>
      </div>
      <div class="header-spacer"></div>
      <button class="collapse-toggle" :title="isCollapsed ? 'Expand' : 'Collapse'">
        <v-icon :icon="isCollapsed ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="16" />
      </button>
    </div>

    <!-- Content Area -->
    <div v-if="!isCollapsed" class="sidebar-content">
      <!-- Loading State -->
      <div v-if="loading && history.length === 0" class="loading-state">
        <div class="loading-shimmer">
          <div class="shimmer-bar"></div>
          <div class="shimmer-bar short"></div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="history.length === 0" class="empty-state">
        <div class="empty-icon-bg">
          <v-icon icon="mdi-text-search-variant" size="24" class="opacity-40" />
        </div>
        <p>No queries found</p>
      </div>

      <!-- History List -->
      <div v-else class="history-list">
        <div
          v-for="item in history"
          :key="item.id"
          class="history-row"
          :class="{ 'is-favorite': item.is_favorite }"
          @click="$emit('select', item)"
        >
          <div class="row-main">
            <div class="row-copy">
              <div class="row-title" :title="item.query_text">
                {{ item.query_text }}
              </div>

              <div class="row-meta">
                <span class="row-date">{{ formatDate(item.last_run_at) }}</span>
                <span v-if="item.results_summary" class="row-summary" :title="formatSummary(item.results_summary)">
                  {{ formatSummary(item.results_summary) }}
                </span>
              </div>
            </div>
          </div>

          <div class="row-actions">
            <button
              class="row-btn"
              :class="{ 'active': item.is_favorite }"
              :title="item.is_favorite ? 'Unsave' : 'Save'"
              @click.stop="toggleFav(item)"
            >
              <v-icon :icon="item.is_favorite ? 'mdi-star' : 'mdi-star-outline'" size="14" />
              <span>{{ item.is_favorite ? 'Saved' : 'Save' }}</span>
            </button>
            <button
              class="row-btn"
              title="Run"
              @click.stop="$emit('execute', item)"
            >
              <v-icon icon="mdi-play" size="14" />
              <span>Run</span>
            </button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Collapsed State Icons -->
    <div v-else class="collapsed-icons" @click="isCollapsed = false">
      <div class="collapsed-icon-wrapper">
        <v-icon icon="mdi-history" size="20" class="icon-dim" />
        <div v-if="favoritesCount > 0" class="mini-fav-badge">{{ favoritesCount }}</div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useHistory } from '@/composables/useHistory'

const emit = defineEmits(['select', 'execute', 'collapse-change'])
const { history, loading, fetchHistory, toggleFavorite } = useHistory()
const isCollapsed = ref(false)

const favoritesCount = computed(() => history.value.filter(h => h.is_favorite).length)

// Emit collapse state changes to parent
watch(isCollapsed, (newVal) => {
  emit('collapse-change', newVal)
})

onMounted(() => {
  fetchHistory()
})

const toggleFav = async (item) => {
  await toggleFavorite(item.id, !item.is_favorite)
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } else {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }
}

const formatSummary = (summary) => {
  if (!summary) return ''

  return summary
    .replace(/^#+\s*/gm, '')
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

defineExpose({ refresh: fetchHistory })
</script>

<style scoped>
/* Main Sidebar Container - off-white, flat */
.history-sidebar {
  position: fixed;
  left: 0;
  top: var(--header-height, 56px);
  bottom: 0;
  width: var(--sidebar-width, 280px);
  background: rgba(255, 255, 255, 0.94);
  border-right: 1px solid var(--border-strong);
  display: flex;
  flex-direction: column;
  transition: width 0.25s ease;
  overflow: hidden;
  z-index: 80;
}

.history-sidebar.is-collapsed {
  width: var(--collapsed-sidebar-width, 48px);
}

/* Sidebar Header */
.sidebar-header {
  height: 44px;
  padding: 0 10px 0 14px;
  display: flex;
  align-items: center;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--border-strong);
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-family-display);
  font-weight: 650;
  font-size: 12px;
  color: var(--text-primary);
  letter-spacing: 0;
}

.title-icon {
  color: var(--text-muted);
}

.count-pill {
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 6px;
  background: #ffffff;
  color: var(--text-muted);
  border: 1px solid var(--border-color);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
}

.header-spacer { flex: 1; }

.collapse-toggle {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.collapse-toggle:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

/* Sidebar Content Area */
.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 10px 10px 16px;
  display: flex;
  flex-direction: column;
}

/* Custom Scrollbar */
.sidebar-content::-webkit-scrollbar { width: 6px; }
.sidebar-content::-webkit-scrollbar-track { background: transparent; }
.sidebar-content::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.08);
  border-radius: 6px;
}
.sidebar-content::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.14);
}

/* History rows */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.history-row {
  position: relative;
  padding: 12px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease, box-shadow 0.12s ease;
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(var(--primary-rgb), 0.035);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.history-row:hover {
  background: rgba(var(--primary-rgb), 0.055);
  border-color: rgba(15, 23, 42, 0.16);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.05);
}

.history-row.is-favorite {
  border-color: rgba(var(--primary-rgb), 0.24);
  background: rgba(var(--primary-rgb), 0.09);
}

.row-main {
  min-width: 0;
  display: block;
}

.row-copy {
  min-width: 0;
}

.row-title {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
  line-height: 1.45;
  letter-spacing: -0.01em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.row-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.35;
  overflow: hidden;
  margin-top: 6px;
}

.row-date {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  min-height: 0;
  padding: 0;
  border-radius: 0;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.row-summary {
  max-width: 100%;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.45;
  padding-left: 10px;
  position: relative;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-summary::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.5em;
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.22);
}

/* Row actions - hover reveal */
.row-actions {
  display: flex;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: none;
}

.row-btn {
  min-width: 0;
  height: 28px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #ffffff;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.row-btn:hover {
  background: var(--surface-muted);
  border-color: rgba(15, 23, 42, 0.18);
  color: var(--text-primary);
}

.row-btn.active {
  color: var(--primary);
  border-color: rgba(var(--primary-rgb), 0.28);
  background: rgba(var(--primary-rgb), 0.06);
}

.row-btn span {
  white-space: nowrap;
}

.history-row:hover .row-title {
  color: var(--text-primary);
}

/* Empty/Loading States */
.empty-state, .loading-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-muted);
  padding: 32px 12px;
}

.empty-icon-bg {
  width: 40px;
  height: 40px;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
  color: var(--text-faint);
}

.empty-state p {
  font-size: 12px;
  font-weight: 400;
  margin: 0;
  color: var(--text-muted);
}

/* Shimmer */
.loading-shimmer {
  width: 100%;
  padding: 8px 4px;
}
.shimmer-bar {
  height: 10px;
  background: linear-gradient(90deg, rgba(15,23,42,0.04) 0%, rgba(15,23,42,0.08) 50%, rgba(15,23,42,0.04) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
  margin-bottom: 8px;
}
.shimmer-bar.short { width: 60%; }

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Collapsed State Icons */
.collapsed-icons {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 8px;
  cursor: pointer;
}

.collapsed-icon-wrapper {
  position: relative;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--text-muted);
  transition: background 0.15s, color 0.15s;
}

.collapsed-icon-wrapper:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.icon-dim { opacity: 1; }

.mini-fav-badge {
  position: absolute;
  top: 0px;
  right: 0px;
  font-size: 8px;
  font-weight: 700;
  background: var(--primary);
  color: white;
  min-width: 12px;
  height: 12px;
  padding: 0 3px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
