<template>
  <aside class="history-sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <div class="sidebar-header">
      <div v-if="!isCollapsed" class="sidebar-title">
        <v-icon icon="mdi-history" size="20" class="title-icon" />
        <span>Recent Queries</span>
      </div>
      <button class="collapse-toggle" @click="isCollapsed = !isCollapsed" :title="isCollapsed ? 'Expand' : 'Collapse'">
        <v-icon :icon="isCollapsed ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="20" />
      </button>
    </div>

    <div v-if="!isCollapsed" class="sidebar-content">
      <div v-if="loading && history.length === 0" class="loading-state">
        <v-progress-circular indeterminate size="24" width="3" color="primary" />
        <p>Loading history...</p>
      </div>
      <div v-else-if="history.length === 0" class="empty-state">
        <v-icon icon="mdi-text-search-variant" size="32" class="mb-2 opacity-20" />
        <p>No queries yet</p>
      </div>
      <div v-else class="history-list">
        <div 
          v-for="item in history" 
          :key="item.id" 
          class="history-item" 
          :class="{ 'is-favorite': item.is_favorite }"
          @click="$emit('select', item)"
        >
          <div class="item-body">
            <div class="item-query" :title="item.query_text">{{ item.query_text }}</div>
            <div v-if="item.results_summary" class="item-summary">{{ item.results_summary }}</div>
            <div class="item-meta">
              <span class="item-date">{{ formatDate(item.created_at) }}</span>
              <v-icon v-if="item.is_favorite" icon="mdi-star" size="10" color="#f59e0b" class="ml-1" />
            </div>
          </div>
          <div class="item-actions">
            <button 
              class="action-btn fav-btn" 
              :class="{ 'active': item.is_favorite }"
              @click.stop="toggleFav(item)"
              :title="item.is_favorite ? 'Remove from favorites' : 'Add to favorites'"
            >
              <v-icon :icon="item.is_favorite ? 'mdi-star' : 'mdi-star-outline'" size="16" />
            </button>
            <button 
              class="action-btn exec-btn" 
              @click.stop="$emit('execute', item)"
              title="Run query again"
            >
              <v-icon icon="mdi-play" size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Collapsed state icon -->
    <div v-else class="collapsed-icons">
      <v-icon icon="mdi-history" size="20" class="mt-4 opacity-50" />
      <div class="fav-count" v-if="favoritesCount > 0">{{ favoritesCount }}</div>
    </div>
  </aside>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useHistory } from '@/composables/useHistory'

const emit = defineEmits(['select', 'execute'])
const { history, favorites, loading, fetchHistory, fetchFavorites, toggleFavorite } = useHistory()
const isCollapsed = ref(false)

const favoritesCount = computed(() => history.value.filter(h => h.is_favorite).length)

onMounted(() => {
  fetchHistory()
})

const formatDate = (dateStr) => {
  const date = new Date(dateStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } else {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }
}

const toggleFav = async (item) => {
  await toggleFavorite(item.id, !item.is_favorite)
}

defineExpose({ refresh: fetchHistory })
</script>

<style scoped>
.history-sidebar {
  width: 300px;
  height: 100%;
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-right: 1px solid rgba(255, 255, 255, 0.3);
  display: flex;
  flex-direction: column;
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  z-index: 90;
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.02);
}

.history-sidebar.is-collapsed {
  width: 64px;
  background: rgba(255, 255, 255, 0.4);
}

.sidebar-header {
  height: 64px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
}

.sidebar-title {
  font-family: var(--font-family-display);
  font-weight: 700;
  font-size: 15px;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  color: #4C64E2;
}

.collapse-toggle {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: rgba(0, 0, 0, 0.03);
  cursor: pointer;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.collapse-toggle:hover {
  background: rgba(76, 100, 226, 0.1);
  color: #4C64E2;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

/* Custom Scrollbar */
.sidebar-content::-webkit-scrollbar {
  width: 4px;
}
.sidebar-content::-webkit-scrollbar-track {
  background: transparent;
}
.sidebar-content::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.05);
  border-radius: 10px;
}
.sidebar-content:hover::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.1);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  position: relative;
  padding: 14px;
  background: #ffffff;
  border-radius: 14px;
  border: 1px solid rgba(0, 0, 0, 0.04);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.01);
}

.history-item:hover {
  border-color: #4C64E2;
  box-shadow: 0 8px 20px rgba(76, 100, 226, 0.08);
  transform: translateY(-2px);
}

.history-item.is-favorite {
  background: linear-gradient(to bottom right, #ffffff, #fffcf0);
  border-left: 4px solid #f59e0b;
}

.item-body {
  flex: 1;
  min-width: 0;
}

.item-query {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
}

.item-summary {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 6px;
  font-style: italic;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-meta {
  display: flex;
  align-items: center;
}

.item-date {
  font-size: 10px;
  font-weight: 500;
  color: #94a3b8;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.item-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-left: 12px;
  opacity: 0;
  transform: translateX(10px);
  transition: all 0.25s ease;
}

.history-item:hover .item-actions {
  opacity: 1;
  transform: translateX(0);
}

.action-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: none;
  background: #f8fafc;
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

.fav-btn.active:hover {
  background: #fef3c7;
}

.exec-btn:hover {
  background: #4C64E2;
  color: white;
}

.loading-state, .empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: #94a3b8;
  text-align: center;
}

.loading-state p, .empty-state p {
  margin-top: 12px;
  font-size: 13px;
  font-weight: 500;
}

.collapsed-icons {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding-top: 10px;
}

.fav-count {
  font-size: 10px;
  font-weight: 800;
  background: #f59e0b;
  color: white;
  padding: 2px 6px;
  border-radius: 10px;
  margin-top: -10px;
}
</style>