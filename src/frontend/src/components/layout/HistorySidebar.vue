<template>
  <aside class="history-sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <div class="sidebar-header">
      <div v-if="!isCollapsed" class="sidebar-title">
        <v-icon icon="mdi-history" size="20" class="mr-2" />
        <span>Query History</span>
      </div>
      <button class="collapse-toggle" @click="isCollapsed = !isCollapsed">
        <v-icon :icon="isCollapsed ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="20" />
      </button>
    </div>

    <div v-if="!isCollapsed" class="sidebar-content">
      <div v-if="loading && history.length === 0" class="loading-state">
        <v-progress-circular indeterminate size="20" width="2" color="primary" />
      </div>
      <div v-else-if="history.length === 0" class="empty-state">
        <p>No recent queries</p>
      </div>
      <div v-else class="history-list">
        <div v-for="item in history" :key="item.id" class="history-item" :class="{ 'is-favorite': item.is_favorite }">
          <div class="item-main" @click="$emit('select', item)">
            <div class="item-query" :title="item.query_text">{{ item.query_text }}</div>
            <div v-if="item.results_summary" class="item-summary">{{ item.results_summary }}</div>
            <div class="item-date">{{ formatDate(item.created_at) }}</div>
          </div>
          <div class="item-actions">
            <button 
              class="action-btn fav-btn" 
              :class="{ 'active': item.is_favorite }"
              @click.stop="toggleFav(item)"
              title="Favorite"
            >
              <v-icon :icon="item.is_favorite ? 'mdi-star' : 'mdi-star-outline'" size="16" />
            </button>
            <button 
              class="action-btn exec-btn" 
              @click.stop="$emit('execute', item)"
              title="Re-execute"
            >
              <v-icon icon="mdi-play" size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useHistory } from '@/composables/useHistory'

const emit = defineEmits(['select', 'execute'])
const { history, loading, fetchHistory, toggleFavorite } = useHistory()
const isCollapsed = ref(false)

onMounted(() => {
  fetchHistory()
})

const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const toggleFav = async (item) => {
  await toggleFavorite(item.id, !item.is_favorite)
}

defineExpose({ refresh: fetchHistory })
</script>

<style scoped>
.history-sidebar {
  width: 280px;
  height: 100%;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  border-right: 1px solid rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  z-index: 100;
}

.history-sidebar.is-collapsed {
  width: 48px;
}

.sidebar-header {
  height: 64px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.sidebar-title {
  font-weight: 700;
  font-size: 14px;
  color: #475569;
  display: flex;
  align-items: center;
}

.collapse-toggle {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
}

.collapse-toggle:hover {
  background: rgba(0, 0, 0, 0.05);
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  padding: 10px;
  background: white;
  border-radius: 10px;
  border: 1px solid rgba(0, 0, 0, 0.05);
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.history-item:hover {
  border-color: #4C64E2;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  transform: translateX(4px);
}

.history-item.is-favorite {
  border-left: 3px solid #f59e0b;
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-query {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.item-summary {
  font-size: 11px;
  color: #64748b;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}

.item-date {
  font-size: 10px;
  color: #94a3b8;
}

.item-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-left: 8px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.history-item:hover .item-actions {
  opacity: 1;
}

.action-btn {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: none;
  background: #f1f5f9;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.fav-btn.active {
  color: #f59e0b;
  background: #fffbeb;
}

.exec-btn:hover {
  background: #4C64E2;
  color: white;
}

.loading-state, .empty-state {
  display: flex;
  justify-content: center;
  padding: 20px;
  color: #94a3b8;
  font-size: 13px;
}
</style>
